# Next

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

## 3. Calibration diagnosis

`src/model.py` has real discrimination (+8.96% Brier skill) but only 2 of 7
probability bins cover. Isotonic made it 3 of 7 and cost skill, so it is not a
mapping problem. Non-stationarity was tested and ruled out — build rate is flat
at 22.2% → 21.3%. Next hypothesis: thin, segment-concentrated high bins
regressing to the mean. Measure it, don't assume it.

## 4. Shared-frailty model

Project outcomes are not independent — they share ISO study cycles,
transmission-owner capex, equipment lead times, state policy. Multiplying
independent probabilities understates tail risk badly. Hierarchical hazard with
random effects at ISO / transmission-owner / study-cycle level turns
"this project is 20%" into "your 40-project book delivers a median 2.1 GW by
2030, 10th percentile 0.9 GW" — which is the question nobody can currently
answer.
