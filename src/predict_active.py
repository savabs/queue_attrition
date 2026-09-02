"""Log a calibrated call on every request still in the queue.

This is the registry doing its job rather than being tested. Every active
interconnection request gets a probability, written down now, resolvable only
by what the ISOs report later -- which the snapshot archive is already
capturing. Nothing here can be revised once written.

Resolution is defined at prediction time: an entry resolves when its ISO
reports a terminal status, observed in data/snapshots/. That makes the archive
the referee rather than a hoard.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import registry as R  # noqa: E402
from baserate import load  # noqa: E402
from diff import KEY_PARTS  # noqa: E402
from model import CAT, NUM, frame, pipe  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "..", "data", "predictions.csv")
MODEL_ID = "logistic-v1"


# A deadline is the only thing that makes a probability falsifiable, so it gets
# the same scrutiny as the probability. Two ways this went wrong before:
#
#   1. Each ISO writes dates its own way, so taking the field raw put 63 of
#      1,636 rows in M/D/YYYY among 1,573 in ISO-8601 -- the same mixed-format
#      trap that destroyed 84% of queue dates in build.py.
#   2. "Proposed Completion Date" is the developer's own claim, and a stalled
#      project keeps the date it missed. 62 rows carried a deadline already in
#      the past, one of them 2002, which is a prediction nothing can falsify.
#
# So: parse per-row rather than infer one format, and floor every deadline at
# the horizon below. Withdrawals run a median 1.5 years, so two years gives the
# majority of the resolvable mass a chance to land while still being a date a
# reader can hold us to.
MIN_HORIZON_YEARS = 2


def resolves_by(proposed, queue_year: int, today: pd.Timestamp | None = None) -> str:
    """The date this call must be settled by, as ISO-8601. Never in the past."""
    today = today or pd.Timestamp.utcnow().tz_localize(None).normalize()
    floor = today + pd.DateOffset(years=MIN_HORIZON_YEARS)

    when = pd.to_datetime(proposed, errors="coerce", format="mixed")
    if pd.isna(when):
        # No claimed date: ISO study cycles run long, so eight years from entry.
        when = pd.Timestamp(year=queue_year + 8, month=12, day=31)
    if getattr(when, "tzinfo", None) is not None:
        when = when.tz_localize(None)

    return max(when, floor).strftime("%Y-%m-%d")


def active_rows() -> pd.DataFrame:
    df = load()
    a = df[df["outcome"] == "active"].copy()
    a["fuel"] = a["Generation Type"].map(__import__("fuel").normalise)
    a["log_mw"] = (a["capacity_mw"].clip(lower=0) + 1).apply(lambda x: __import__("numpy").log(x))
    to = a["Transmission Owner"].astype(str).str.strip().str.upper()
    counts = to.value_counts()
    a["to_top"] = to.where(to.map(counts) >= 40, "OTHER")
    a["log_mw"] = a["log_mw"].fillna(a["log_mw"].median())
    a["queue_year"] = a["queue_year"].fillna(a["queue_year"].median())
    return a


def main() -> None:
    train = frame()
    model = pipe().fit(train[CAT + NUM], train["y"])
    print(f"trained on {len(train):,} resolved requests "
          f"(base rate {train['y'].mean():.1%})")

    a = active_rows()
    p = model.predict_proba(a[CAT + NUM])[:, 1]
    a = a.assign(p=p)

    # Queue ID alone is not unique -- MISO carries J2656 twice at different
    # capacities, ISONE reuses positions across whole plants. The registry
    # refuses a second call on one entity_id, so identity here has to match the
    # composite the differ already uses or real projects get silently dropped.
    parts = [c for c in KEY_PARTS if c in a.columns]
    ident = a[parts].fillna("").astype(str).agg("|".join, axis=1)
    a = a.assign(_eid=a["iso"] + ":" + ident)

    dupes = a["_eid"].duplicated().sum()
    if dupes:
        print(f"note: {dupes} rows share an identity even composite-keyed; "
              "keeping the first of each, they are excluded from the book below")
        a = a[~a["_eid"].duplicated()]

    already = {(r["domain"], r["entity_id"]) for r in R.read(LEDGER)}
    logged = skipped = 0
    for _, row in a.iterrows():
        eid = row["_eid"]
        if ("interconnection", eid) in already:
            skipped += 1
            continue
        already.add(("interconnection", eid))
        by = resolves_by(row.get("Proposed Completion Date"), int(row["queue_year"]))
        R.log(
            LEDGER, domain="interconnection", entity_id=eid,
            entity_name=str(row.get("Project Name") or "")[:80],
            p=float(row["p"]), model=MODEL_ID,
            features_json=(f'{{"iso":"{row["iso"]}","fuel":"{row["fuel"]}",'
                           f'"mw":{row["capacity_mw"]},"queue_year":{int(row["queue_year"])}}}'),
            thesis="", resolves_by=by,
            outcome_source="ISO queue terminal status, observed in data/snapshots/",
        )
        logged += 1

    print(f"logged {logged:,} new predictions, skipped {skipped:,} already present")
    print(f"ledger: {os.path.relpath(LEDGER)}\n")

    dist = pd.cut(a["p"], [0, .05, .1, .2, .3, .5, 1.0])
    print("distribution of the calls just made:")
    print(dist.value_counts().sort_index().to_string())
    print(f"\nexpected builds across the book: {a['p'].sum():,.0f} of {len(a):,} requests")
    print(f"expected MW delivered: {(a['p'] * a['capacity_mw']).sum():,.0f} "
          f"of {a['capacity_mw'].sum():,.0f} MW queued "
          f"({(a['p'] * a['capacity_mw']).sum() / a['capacity_mw'].sum():.1%})")


if __name__ == "__main__":
    main()
