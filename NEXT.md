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

## 4. Shared-frailty model — BUILT

`src/frailty.py`. Correlation measured before fitting (permutation null, all
levels p < 0.00025), tau fitted by marginal ML, structure chosen by
out-of-sample portfolio coverage. Live book: 4.3x wider than independence, P10
21.6 GW worse. See README.

Open follow-ons:
- The capacity bias is +6.1% after MW-weighted calibration, not zero. Worth
  another pass — possibly a separate model for delivered MW rather than a
  re-calibration of a count model.
- Levels are fitted marginally and overlap. A properly crossed random-effects
  fit would give cleaner taus; Monte Carlo EM, since Gauss-Hermite does not
  factor across crossed levels.
- PIT on random books is ~0.19 for every structure including independence,
  which is marginal miscalibration, not a dependence problem. Same root cause
  as item 3.

## 5. Redistribution terms — check before this earns money

PJM's Data Miner page says outright: *"redistribution of information and or
derived from Data Miner is strictly prohibited without an active PJM
Membership. A minimum level of Associate Membership is required."* Non-members
may query it at 6 connections/minute, but may not republish anything derived
from it.

That is why PJM is parked rather than pending. The API key was never the
blocker; the licence is. Getting the key would have supplied data the public
ledger cannot legally use, which is worse than not having it, because the
problem surfaces only after something is built on top. The real question is
what Associate Membership costs and whether it permits publication — a call to
Member Relations (866-400-8980), not a registration form.

**The open item is the other four.** MISO, CAISO, NYISO and ISO-NE data is
already being republished in derived form at tirramind.com/predictions. Their
terms have not been read. Do that before this is commercial, and record what
each one permits. Independent aggregators are not a precedent worth relying on
— interconnection.fyi's own terms prohibit exactly the redistribution it
performs.
