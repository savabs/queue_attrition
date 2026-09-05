"""Did this run actually capture anything?

`snapshot.py` exits 0 even when every single ISO fails, because a failure is
recorded as a row in index.jsonl rather than raised. That is the right design
for the archive -- an outage is data -- but it means the process exit code
cannot be used to decide whether the job worked.

So this reads back what the run wrote and fails on row counts, not on status.
The rule the archive lives by: never report success without counting rows.

Exit 0 -- at least one ISO captured (new or unchanged).
Exit 1 -- nothing captured. History is being lost right now.
"""
import json
import os
import sys
from collections import Counter

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "data", "snapshots", "index.jsonl")


def main() -> int:
    if not os.path.exists(INDEX):
        print("FAIL: no index.jsonl — the archive has never been written")
        return 1

    with open(INDEX) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        print("FAIL: index.jsonl is empty")
        return 1

    # One run writes one row per ISO, all sharing a captured_at.
    latest = max(r["captured_at"] for r in rows)
    run = [r for r in rows if r["captured_at"] == latest]
    tally = Counter(r["status"] for r in run)
    ok = tally["new"] + tally["unchanged"]

    print(f"run {latest}")
    for r in sorted(run, key=lambda r: r["iso"]):
        if r["status"] == "fail":
            print(f"  {r['iso']:6} FAIL  {r.get('error', '')[:90]}")
        else:
            print(f"  {r['iso']:6} {r['status']:9} {r.get('rows', 0):>6} rows")
    print(f"captured {ok}/{len(run)} sources "
          f"({tally['new']} new, {tally['unchanged']} unchanged, {tally['fail']} failed)")

    if ok == 0:
        print("FAIL: zero sources captured — every ISO failed. "
              "A day lost here cannot be recovered by anyone, including the ISO.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
