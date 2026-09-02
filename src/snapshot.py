"""Immutable daily snapshots of every queue. This is the asset.

The ISOs publish CURRENT STATE ONLY. A project's status, study phase,
capacity and in-service date are overwritten in place on every refresh. When
a 400 MW request is revised to 250 MW, or a 2027 in-service date slips to
2029, the previous value is not archived anywhere -- not by gridstatus, not by
the aggregators, not by the ISO.

So the revision history cannot be bought, scraped later, or reconstructed. It
can only be accumulated, starting from the first day someone bothers. Every
day without a snapshot is a day of history that is gone permanently.

Snapshots are append-only and content-addressed. A refresh that returns
identical bytes does not create a new file, so an ISO that goes quiet for a
week costs nothing and is still visible as a gap in the index.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from fetch import SOURCES

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "..", "data", "snapshots")
INDEX = os.path.join(ARCHIVE, "index.jsonl")


def _digest(df: pd.DataFrame) -> str:
    """Hash the content, not the file: identical data must hash identically
    regardless of row order or how pandas felt about column dtypes today."""
    canonical = df.reindex(sorted(df.columns), axis=1)
    canonical = canonical.sort_values(list(canonical.columns), kind="stable")
    return hashlib.sha256(
        canonical.to_csv(index=False).encode("utf-8")
    ).hexdigest()[:16]


def snapshot(only=None) -> list:
    os.makedirs(ARCHIVE, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    seen = _already_have()
    written = []

    for iso, cls in SOURCES.items():
        if only and iso not in only:
            continue
        try:
            df = cls().get_interconnection_queue()
        except Exception as e:  # noqa: BLE001
            _record({"captured_at": now.isoformat(timespec="seconds"), "iso": iso,
                     "status": "fail", "error": f"{type(e).__name__}: {str(e)[:160]}",
                     "rows": 0, "digest": None, "path": None})
            print(f"{iso:<6} FAIL  {type(e).__name__}: {str(e)[:70]}")
            continue

        dg = _digest(df)
        if dg in seen.get(iso, set()):
            _record({"captured_at": now.isoformat(timespec="seconds"), "iso": iso,
                     "status": "unchanged", "rows": len(df), "digest": dg,
                     "path": None, "error": None})
            print(f"{iso:<6} {len(df):>6} rows  unchanged ({dg})")
            continue

        path = os.path.join(ARCHIVE, iso, f"{day}_{dg}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)
        _record({"captured_at": now.isoformat(timespec="seconds"), "iso": iso,
                 "status": "new", "rows": len(df), "digest": dg,
                 "path": os.path.relpath(path, ARCHIVE), "error": None})
        written.append((iso, len(df), dg))
        print(f"{iso:<6} {len(df):>6} rows  NEW -> {os.path.relpath(path, ARCHIVE)}")

    return written


def _already_have() -> dict:
    seen = {}
    if os.path.exists(INDEX):
        with open(INDEX) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("digest"):
                    seen.setdefault(r["iso"], set()).add(r["digest"])
    return seen


def _record(row: dict) -> None:
    with open(INDEX, "a") as fh:
        fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    snapshot(only=sys.argv[1:] or None)
