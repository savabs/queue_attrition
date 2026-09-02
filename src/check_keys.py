"""Verify credentials actually work, before trusting the nightly job to use them.

A key that is present but wrong fails at 09:15 with a network-shaped error and
looks identical to the source being down. This tests each one against the real
endpoint and says which of the three currently-missing ISOs it unlocks.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from env import load  # noqa: E402

load()


def check_pjm() -> tuple:
    key = os.environ.get("PJM_API_KEY")
    if not key:
        return "PJM", "absent", "set PJM_API_KEY in .env — see .env.example"
    try:
        import gridstatus
        df = gridstatus.PJM(api_key=key).get_interconnection_queue()
        return "PJM", "OK", f"{len(df):,} queue rows"
    except Exception as e:  # noqa: BLE001
        return "PJM", "FAIL", f"{type(e).__name__}: {str(e)[:110]}"


def check_eia() -> tuple:
    key = os.environ.get("EIA_API_KEY")
    if not key:
        return "EIA", "absent", "set EIA_API_KEY in .env — see .env.example"
    try:
        import urllib.request
        import json
        url = ("https://api.eia.gov/v2/electricity/operating-generator-capacity/"
               f"data/?api_key={key}&frequency=monthly&data[0]=nameplate-capacity-mw&length=1")
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.load(r)
        n = body.get("response", {}).get("total")
        return "EIA", "OK", f"reachable, {n} records available"
    except Exception as e:  # noqa: BLE001
        return "EIA", "FAIL", f"{type(e).__name__}: {str(e)[:110]}"


if __name__ == "__main__":
    bad = 0
    for name, status, detail in (check_pjm(), check_eia()):
        mark = {"OK": "✓", "absent": "·", "FAIL": "✗"}[status]
        print(f"{mark} {name:<5} {status:<7} {detail}")
        bad += status == "FAIL"
    print("\nnote: ERCOT and SPP are not credential problems — ERCOT blocks "
          "scripted access outright,\n      and SPP's ops portal times out. No key fixes either.")
    sys.exit(1 if bad else 0)
