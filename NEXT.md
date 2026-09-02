# Next

The ledger is live: <https://tirramind.com/predictions> — 1,636 open calls,
355 GW, nothing resolved. Frozen from 2026-09-02; a modelling change gets a new
model ID, not a rewritten file.


## 1. PJM API key  ← the open one

Three minutes, free, non-members welcome.

1. <https://apiportal.pjm.com/> → Sign in → create a PJM account
2. Verify the email PJM sends
3. Profile → subscriptions → reveal the **Primary key**
4. Paste into `.env`: `PJM_API_KEY=<key>`
5. `./venv/bin/python src/check_keys.py`

PJM is the largest datacenter market that publishes a queue at all, and it is
the only one of the three missing ISOs a credential fixes — ERCOT blocks
scripted access, SPP's portal times out. The nightly job picks it up by itself
from the next run.

## 2. EIA API key

<https://www.eia.gov/opendata/register.php> — instant, no approval step.

Unblocks matching queue rows to EIA-860 plants, which gives an *independent*
verdict on whether a project was actually built rather than trusting each ISO's
bookkeeping. Also unblocks time-to-event survival: only 370 of 1,326 builds
currently carry a completion date, and MISO and ISONE publish none.

## 3. Calibration — the direction is now known

`src/model.py` has real discrimination (+7.7% Brier skill, 0.1540 vs 0.1668)
but only 2 of 7 probability bins cover. **It ranks well and quantifies badly.**

The direction is over-spreading, in both tails at once:

| model says | n | actual | verdict |
|---|---|---|---|
| 0–5% | 794 | 4.3% | too low |
| 5–10% | 959 | 10.7% | too low |
| 20–30% | 999 | 27.7% | too low |
| 30–50% | 809 | 35.0% | too high |
| **above 50%** | 352 | **49.4%** | **far too high** |

Above 50% it says 65 and means 49. Its confidence outruns its evidence at the
top and the same over-spreading makes it too gloomy at the bottom.

Ruled out: non-stationarity (build rate flat, 22.2% → 21.3%); a mapping fix
(isotonic bought one bin and cost skill). Live hypothesis: the high bins are
thin and concentrated in a few segments, so they regress to the mean out of
sample. Measure that, don't assume it — check whether the >50% bin collapses
onto a small number of (iso, fuel) cells.

Published as-is at <https://tirramind.com/predictions>, failure included.

## 4. Shared-frailty model

Project outcomes are not independent — they share ISO study cycles,
transmission-owner capex, equipment lead times, state policy. Multiplying
independent probabilities understates tail risk badly. Hierarchical hazard with
random effects at ISO / transmission-owner / study-cycle level turns
"this project is 20%" into "your 40-project book delivers a median 2.1 GW by
2030, 10th percentile 0.9 GW" — which is the question nobody can currently
answer.
