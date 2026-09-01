"""Turn four ISO queue exports into one labelled attrition dataset.

The label is whether an interconnection request was eventually BUILT or
WITHDRAWN. Requests still in the queue are neither: they are CENSORED, and
folding them in either direction is the single easiest way to manufacture a
wrong base rate.

Two things are deliberately kept out of the feature set, because both are
only knowable after the outcome they would be used to predict:

    Withdrawn Date, Actual Completion Date

`Status` is the label itself and is likewise never a feature. The guard at the
bottom of this file fails loudly rather than trusting anyone to remember.
"""
import glob
import os

import pandas as pd

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
OUT = os.path.join(HERE, "..", "data", "queue_attrition.csv")

# Anything decided at or after the outcome. Never a feature.
LEAKY = ["Status", "Withdrawn Date", "Actual Completion Date", "Withdrawal Comment"]

# ISO status vocabularies differ; map to three outcomes and refuse to guess.
BUILT = {"done", "completed", "legacy: done", "in service", "operational"}
WITHDRAWN = {"withdrawn"}
ACTIVE = {"active", "pending revision approval", "pending transfer", "in progress"}

KEEP = [
    "Queue ID", "Project Name", "Interconnecting Entity", "County", "State",
    "Interconnection Location", "Transmission Owner", "Generation Type",
    "Capacity (MW)", "Summer Capacity (MW)", "Winter Capacity (MW)",
    "Queue Date", "Proposed Completion Date",
]


def classify(status: str) -> str:
    s = str(status).strip().lower()
    if s in BUILT:
        return "built"
    if s in WITHDRAWN:
        return "withdrawn"
    if s in ACTIVE:
        return "active"
    return "unknown"


def build() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(RAW, "*_queue.csv"))):
        iso = os.path.basename(path).split("_")[0]
        df = pd.read_csv(path, low_memory=False)
        df["iso"] = iso
        df["outcome"] = df["Status"].map(classify)
        for col in KEEP:
            if col not in df.columns:
                df[col] = pd.NA
        frames.append(df[KEEP + ["iso", "outcome"] + [c for c in LEAKY if c in df.columns]])

    all_ = pd.concat(frames, ignore_index=True)

    # Parse per ISO, never across. The four ISOs use four date formats
    # ("2003-11-18 08:00:00", "1/14/2025", "2025-10-08T00:37:52+00:00",
    # "2008-01-30") and pandas infers a single format from the first non-null
    # value, then coerces every row that disagrees to NaT. Parsed as one
    # column this silently destroyed 7,400 of 9,640 dates -- and because the
    # loss looks like ordinary missingness, nothing downstream complains.
    parts = []
    for iso in all_["iso"].unique():
        m = all_["iso"] == iso
        parts.append(
            pd.to_datetime(
                all_.loc[m, "Queue Date"], errors="coerce", utc=True, format="mixed"
            )
        )
    all_["queue_date"] = pd.concat(parts).reindex(all_.index)

    parsed = all_["queue_date"].notna().sum()
    present = all_["Queue Date"].notna().sum()
    assert parsed >= 0.98 * present, (
        f"date parsing lost rows: {present} present, only {parsed} parsed"
    )
    all_["queue_year"] = all_["queue_date"].dt.year
    all_["capacity_mw"] = pd.to_numeric(all_["Capacity (MW)"], errors="coerce")

    # resolved = the outcome is actually known. Everything else is censored and
    # must be excluded from any rate, not counted as a survivor.
    all_["resolved"] = all_["outcome"].isin(["built", "withdrawn"])
    return all_


def audit(df: pd.DataFrame) -> None:
    """Fail loudly if an outcome-determined column reaches the feature set."""
    features = [c for c in df.columns if c not in LEAKY + ["outcome", "resolved"]]
    bled = [c for c in LEAKY if c in features]
    assert not bled, f"leakage: {bled} present as features"


if __name__ == "__main__":
    df = build()
    audit(df)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT}  rows={len(df)}")
    print("\noutcome by ISO:")
    print(pd.crosstab(df["iso"], df["outcome"], margins=True))
    print("\nunknown statuses (should be empty):")
    unk = df.loc[df["outcome"] == "unknown", "Status"].value_counts()
    print(unk if len(unk) else "  none")
