"""Pull interconnection queues from every ISO that serves them publicly.

Each ISO is fetched independently and failures are reported, not raised: the
point is to know exactly which sources are obtainable without credentials,
because that is what the dataset can honestly be built from.

CSV, not parquet: the ISO queue IDs are genuinely mixed-type ("643R" in CAISO,
bare ints in NYISO) and arrow refuses them. Keeping the raw text avoids
inventing a type the source does not have.
"""
import os
import sys
import warnings
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

warnings.filterwarnings("ignore")

import gridstatus  # noqa: E402

from env import load as _load_env  # noqa: E402

_load_env()

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# PJM needs PJM_API_KEY (free, but a credential). ERCOT 403s all scripted
# access. SPP's ops portal times out from here. All three are recorded as
# misses rather than quietly dropped.
SOURCES = {
    "MISO": gridstatus.MISO,
    "NYISO": gridstatus.NYISO,
    "CAISO": gridstatus.CAISO,
    "ISONE": gridstatus.ISONE,
    "SPP": gridstatus.SPP,
    "PJM": gridstatus.PJM,
    "ERCOT": gridstatus.Ercot,
}


def fetch_all(only=None):
    os.makedirs(RAW, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []
    for name, cls in SOURCES.items():
        if only and name not in only:
            continue
        try:
            df = cls().get_interconnection_queue()
            path = os.path.join(RAW, f"{name}_queue.csv")
            df.to_csv(path, index=False)
            results.append((name, len(df), "ok", ""))
            print(f"{name:<6} {len(df):>6} rows -> {os.path.relpath(path)}")
        except Exception as e:  # noqa: BLE001 - reporting, not handling
            results.append((name, 0, "fail", f"{type(e).__name__}: {e}"))
            print(f"{name:<6} {'':>6}      FAIL {type(e).__name__}: {str(e)[:90]}")

    with open(os.path.join(RAW, "_fetch_log.csv"), "a") as fh:
        for name, n, status, err in results:
            fh.write(f"{stamp},{name},{n},{status},\"{err[:200]}\"\n")
    return results


if __name__ == "__main__":
    fetch_all(only=sys.argv[1:] or None)
