"""Base rates, computed the way that survives scrutiny.

The naive number -- built / (built + withdrawn) over everything -- is wrong in
two directions at once:

  1. Recent cohorts are censored. A request filed in 2024 has not had time to
     be built, so counting it as "not yet built" understates the build rate.
  2. Old cohorts are cleaner but may not describe today's queue at all.

So every rate here is reported per queue-year cohort, alongside how much of
that cohort has actually resolved. A cohort that is 40% unresolved does not
get to contribute a build rate.
"""
import os

import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data", "queue_attrition.csv")

# A cohort is only quoted when this share of it has reached a terminal state.
RESOLUTION_FLOOR = 0.90


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA, low_memory=False)
    # build.py already parsed this per ISO and wrote it back as ISO-8601;
    # re-parsing the raw per-ISO text here would reintroduce the format bug.
    df["queue_date"] = pd.to_datetime(df["queue_date"], errors="coerce", utc=True)
    df["queue_year"] = df["queue_date"].dt.year
    df["capacity_mw"] = pd.to_numeric(df["Capacity (MW)"], errors="coerce")
    return df


def missingness_check(df: pd.DataFrame) -> pd.DataFrame:
    """Is a missing queue date independent of outcome? If not, cohorts lie."""
    df = df.assign(no_date=df["queue_date"].isna())
    return pd.crosstab(df["outcome"], df["no_date"], normalize="index").rename(
        columns={False: "has_date", True: "MISSING_date"}
    )


def cohorts(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["queue_year"])
    g = d.groupby("queue_year")["outcome"].value_counts().unstack(fill_value=0)
    for c in ("built", "withdrawn", "active"):
        if c not in g:
            g[c] = 0
    g["n"] = g[["built", "withdrawn", "active"]].sum(axis=1)
    g["resolved_share"] = (g["built"] + g["withdrawn"]) / g["n"]
    g["build_rate"] = g["built"] / (g["built"] + g["withdrawn"]).replace(0, pd.NA)
    g["quotable"] = g["resolved_share"] >= RESOLUTION_FLOOR
    return g[["n", "built", "withdrawn", "active", "resolved_share", "build_rate", "quotable"]]


if __name__ == "__main__":
    df = load()
    res = df[df["outcome"].isin(["built", "withdrawn"])]

    print("=" * 68)
    print("NAIVE (what gets quoted)")
    print("=" * 68)
    n_b, n_w = (res["outcome"] == "built").sum(), (res["outcome"] == "withdrawn").sum()
    print(f"  resolved requests : {len(res):,}")
    print(f"  built             : {n_b:,}")
    print(f"  withdrawn         : {n_w:,}")
    print(f"  naive build rate  : {n_b / len(res):.1%}")
    mw = res.groupby("outcome")["capacity_mw"].sum()
    print(f"  by capacity       : {mw.get('built', 0) / mw.sum():.1%} of MW built")

    print()
    print("=" * 68)
    print("MISSING QUEUE DATE vs OUTCOME  (if these differ, cohorts are biased)")
    print("=" * 68)
    print(missingness_check(df).round(3).to_string())

    print()
    print("=" * 68)
    print(f"BY COHORT  (quotable = >={RESOLUTION_FLOOR:.0%} resolved)")
    print("=" * 68)
    c = cohorts(df)
    print(c.tail(22).to_string(float_format=lambda x: f"{x:.3f}"))

    q = c[c["quotable"]]
    if len(q):
        built, wd = q["built"].sum(), q["withdrawn"].sum()
        print()
        print("=" * 68)
        print(f"QUOTABLE COHORTS ONLY ({int(q.index.min())}-{int(q.index.max())})")
        print("=" * 68)
        print(f"  n={built + wd:,}   build rate = {built / (built + wd):.1%}")

        # Records with no queue date fall out of every cohort. They are almost
        # all withdrawals (old NYISO rows), so dropping them pushes the build
        # rate UP. The honest quote is a range, not the convenient end of it.
        undated = df[df["queue_date"].isna() & df["outcome"].isin(["built", "withdrawn"])]
        u_b = (undated["outcome"] == "built").sum()
        u_w = (undated["outcome"] == "withdrawn").sum()
        lo = (built + u_b) / (built + wd + u_b + u_w)
        print(f"  undated resolved records excluded: {len(undated):,} "
              f"({u_b} built / {u_w} withdrawn)")
        print(f"  if all of them belonged to quotable cohorts: {lo:.1%}")
        print()
        print(f"  ==> defensible range: {lo:.1%} - {built / (built + wd):.1%}")
        print(f"  ==> the naive figure ({n_b / len(res):.1%}) sits below both, "
              "because censoring\n      counts unresolved recent requests as failures.")
