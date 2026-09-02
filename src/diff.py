"""Turn two snapshots into change events.

This is the output the archive exists to produce. A queue row is not
interesting; a queue row that CHANGED is. A 400 MW request revised to 250, an
in-service date that slips a year, a project that quietly leaves the queue --
none of these are visible in any current-state feed, because the previous
value has already been overwritten at the source.

Changes are reported per field, with both values, so every event can be
checked against the two snapshots it came from rather than believed.
"""
import argparse
import glob
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "..", "data", "snapshots")

# `Queue ID` is NOT a primary key. ISONE reuses one position across many units
# (position "73" covers eight plants); NYISO leaves it null on 1,350 historical
# rows and reuses "0031" for Astoria Phase 1 and Phase 2. Diffing on it alone
# silently reports one project mutating into a different one -- which would
# have corrupted every change event in the archive, invisibly.
#
# So identity is a composite, widened until it is unique, and rows that cannot
# be made unique are reported rather than guessed at.
# Only identity-stable fields belong here. A field that is watched for change
# must never be part of the key: with "Capacity (MW)" in the key, a 400->250 MW
# revision reads as one project leaving and a different one arriving, which is
# precisely the event the archive exists to capture. Asserted below.
KEY_PARTS = ["Queue ID", "Project Name", "County",
             "Interconnection Location", "Queue Date"]

# Fields whose movement is the point. Everything else is noise or cosmetics.
WATCH = [
    "Status",
    "Capacity (MW)",
    "Proposed Completion Date",
    "inService",
    "studyPhase",
    "Transmission Owner",
    "Generation Type",
    "Interconnection Approval Date",
]


assert not (set(KEY_PARTS) & set(WATCH)), (
    f"identity key and watch list overlap on {set(KEY_PARTS) & set(WATCH)}: "
    "a change in a key field would be reported as a departure plus an arrival"
)


def _load(path: str):
    """Return (indexed frame, unkeyable rows). Never silently drops a row."""
    df = pd.read_csv(path, low_memory=False, dtype=str)
    parts = [c for c in KEY_PARTS if c in df.columns]
    if not parts:
        raise SystemExit(f"{path}: none of {KEY_PARTS} present")

    # Widen the key one column at a time and stop as soon as it is unique, so
    # the key stays as narrow -- and as stable across refreshes -- as possible.
    used = []
    for c in parts:
        used.append(c)
        key = df[used].fillna("\0").agg("|".join, axis=1)
        if not key.duplicated().any():
            break

    dup_mask = key.duplicated(keep=False)
    unkeyable = df[dup_mask]
    keyed = df[~dup_mask].copy()
    keyed.index = key[~dup_mask]
    keyed.index.name = "row_key"
    return keyed, unkeyable, used


def compare(old_path: str, new_path: str) -> pd.DataFrame:
    old, old_bad, used_o = _load(old_path)
    new, new_bad, used_n = _load(new_path)
    if used_o != used_n:
        print(f"  note: key differs between snapshots ({used_o} vs {used_n}); "
              "using the wider one is not safe, so only shared columns are compared")
    if len(old_bad) or len(new_bad):
        print(f"  note: {len(old_bad)} + {len(new_bad)} rows have no unique key "
              "and are excluded from change tracking (not dropped from the archive)")
    print(f"  identity key: {' + '.join(used_n)}")
    fields = [f for f in WATCH if f in old.columns and f in new.columns]

    events = []
    for qid in new.index.difference(old.index):
        events.append({"queue_id": qid, "event": "entered", "field": None,
                       "old": None, "new": None})
    for qid in old.index.difference(new.index):
        events.append({"queue_id": qid, "event": "left", "field": None,
                       "old": None, "new": None})

    both = old.index.intersection(new.index)
    o, n = old.loc[both, fields], new.loc[both, fields]
    for f in fields:
        # NaN != NaN, so compare on filled strings or every null looks changed.
        a, b = o[f].fillna("\0"), n[f].fillna("\0")
        moved = both[(a.values != b.values)]
        for qid in moved:
            events.append({"queue_id": qid, "event": "changed", "field": f,
                           "old": old.at[qid, f], "new": new.at[qid, f]})

    return pd.DataFrame(events, columns=["queue_id", "event", "field", "old", "new"])


def latest_two(iso: str):
    files = sorted(glob.glob(os.path.join(ARCHIVE, iso, "*.csv")))
    if len(files) < 2:
        return None
    return files[-2], files[-1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--old", help="explicit older snapshot (default: second-newest)")
    ap.add_argument("--new", help="explicit newer snapshot (default: newest)")
    a = ap.parse_args()

    if a.old and a.new:
        pair = (a.old, a.new)
    else:
        pair = latest_two(a.iso)
        if not pair:
            raise SystemExit(
                f"{a.iso}: need two snapshots to diff, have "
                f"{len(glob.glob(os.path.join(ARCHIVE, a.iso, '*.csv')))}. "
                "Run src/snapshot.py again tomorrow."
            )

    print(f"{os.path.basename(pair[0])}  ->  {os.path.basename(pair[1])}")
    ev = compare(*pair)
    if ev.empty:
        print("no changes")
        raise SystemExit(0)

    print(f"\n{len(ev)} change events")
    print(ev["event"].value_counts().to_string())
    ch = ev[ev["event"] == "changed"]
    if not ch.empty:
        print("\nby field:")
        print(ch["field"].value_counts().to_string())
        print("\nsample:")
        print(ch.head(12).to_string(index=False, max_colwidth=30))
