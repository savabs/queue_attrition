"""Where the attrition actually differs.

A single 17-21% base rate is not a product. The question a buyer has is
narrower: given THIS request -- this fuel, this size, this ISO, this
transmission owner -- what is the chance it gets built?

Every rate here is restricted to cohorts that have substantially resolved,
for the same censoring reason as in baserate.py. Segments below MIN_N are
printed but marked, because a 3-of-4 build rate is not a finding.
"""
import os

import numpy as np
import pandas as pd

from baserate import RESOLUTION_FLOOR, cohorts, load

MIN_N = 40


def resolved_mature(df: pd.DataFrame) -> pd.DataFrame:
    """Resolved requests from cohorts old enough to quote."""
    c = cohorts(df)
    good = set(c.index[c["quotable"]])
    return df[df["outcome"].isin(["built", "withdrawn"]) & df["queue_year"].isin(good)]


def rate_table(df: pd.DataFrame, by: str, label: str) -> pd.DataFrame:
    g = df.groupby(by)["outcome"].value_counts().unstack(fill_value=0)
    for c in ("built", "withdrawn"):
        if c not in g:
            g[c] = 0
    g["n"] = g["built"] + g["withdrawn"]
    g["build_rate"] = g["built"] / g["n"]
    # Wilson interval: n is small in several segments and the normal
    # approximation misbehaves badly near 0, which is exactly where
    # these rates live.
    z = 1.96
    p, n = g["build_rate"], g["n"]
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    g["lo95"], g["hi95"] = (centre - half).clip(0, 1), (centre + half).clip(0, 1)
    g["thin"] = g["n"] < MIN_N
    out = g[["n", "built", "build_rate", "lo95", "hi95", "thin"]].sort_values(
        "n", ascending=False
    )
    print(f"\n--- {label} ---")
    print(out.head(14).to_string(float_format=lambda x: f"{x:.3f}"))
    return out


def mw_band(mw):
    if pd.isna(mw):
        return "unknown"
    for hi, name in ((20, "<20"), (100, "20-100"), (300, "100-300"), (1000, "300-1000")):
        if mw < hi:
            return name
    return ">=1000"


if __name__ == "__main__":
    df = load()
    m = resolved_mature(df)
    print(f"resolved requests in quotable cohorts: {len(m):,} "
          f"(of {len(df):,} total, floor={RESOLUTION_FLOOR:.0%})")
    print(f"overall build rate in this set: {(m['outcome'] == 'built').mean():.1%}")

    rate_table(m, "iso", "by ISO")

    fuel = m.assign(fuel=m["Generation Type"].astype(str).str.strip().str.title())
    rate_table(fuel[fuel["fuel"] != "Nan"], "fuel", "by generation type")

    band = m.assign(band=m["capacity_mw"].map(mw_band))
    order = ["<20", "20-100", "100-300", "300-1000", ">=1000", "unknown"]
    t = rate_table(band, "band", "by capacity band")
    print("\n  (ordered by size)")
    print(t.reindex([b for b in order if b in t.index]).to_string(
        float_format=lambda x: f"{x:.3f}"))

    to = m.assign(to=m["Transmission Owner"].astype(str).str.strip())
    big = to[to["to"].map(to["to"].value_counts()) >= MIN_N]
    rate_table(big, "to", f"by transmission owner (n>={MIN_N})")
