"""Is the archive actually still running?

A snapshot job that dies quietly is the one failure that cannot be repaired
later -- you cannot go back and collect Tuesday. So the gap since each ISO's
last successful capture is reported explicitly, and the exit code is non-zero
when anything has gone stale, so a wrapper or a glance at the log can catch it.

Sources that have never succeeded (PJM needs a key, ERCOT blocks scripts) are
listed separately: they are known misses, not regressions.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "data", "snapshots", "index.jsonl")

# Queues refresh weekly-to-monthly, so a few quiet days is normal; two weeks
# without even a successful FETCH means the job is broken, not the source.
STALE_DAYS = 14


def read():
    if not os.path.exists(INDEX):
        return []
    out = []
    with open(INDEX) as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main() -> int:
    rows = read()
    if not rows:
        print("no snapshots recorded yet — run scripts/daily_snapshot.sh")
        return 1

    now = datetime.now(timezone.utc)
    isos = sorted({r["iso"] for r in rows})
    stale, never = [], []

    print(f"{'iso':<8} {'last ok':<22} {'age':>6}  {'captures':>8}  status")
    for iso in isos:
        ok = [r for r in rows if r["iso"] == iso and r["status"] in ("new", "unchanged")]
        files = len({r["digest"] for r in ok if r.get("digest")})
        if not ok:
            last_err = [r for r in rows if r["iso"] == iso][-1].get("error") or ""
            print(f"{iso:<8} {'never':<22} {'-':>6}  {0:>8}  {last_err[:44]}")
            never.append(iso)
            continue
        last = max(datetime.fromisoformat(r["captured_at"]) for r in ok)
        age = (now - last).days
        flag = "STALE" if age > STALE_DAYS else "ok"
        if flag == "STALE":
            stale.append((iso, age))
        print(f"{iso:<8} {last.strftime('%Y-%m-%d %H:%M UTC'):<22} {age:>4}d  "
              f"{files:>8}  {flag}")

    runs = sorted({r["captured_at"][:10] for r in rows})
    print(f"\ndistinct days the job has run: {len(runs)}"
          f"   first {runs[0]}   last {runs[-1]}")
    if never:
        print(f"never captured (known misses): {', '.join(never)}")
    if stale:
        print("\nSTALE — history is being lost right now:")
        for iso, age in stale:
            print(f"  {iso}: {age} days since last successful capture")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
