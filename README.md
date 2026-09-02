# Queue attrition

How often does a US interconnection request actually get built?

Everyone quotes the queue headline — *"466 GW in ERCOT"*, *"699 GW in MISO"* —
as if it were a pipeline. Most of it never gets built. This measures how much.

**Answer: 17.2%–21.4% of resolved requests were built.** The naive figure is
14.2%, and it is wrong for a specific reason given below.

**The number that matters for the AI-power trade: requests of 1,000 MW or more
were built 5.3% of the time (95% CI 2.8–9.8, n=169).**

## What the data is

Four ISOs publish their full interconnection queue with outcomes, no
credentials required:

| ISO | requests | built | withdrawn | still active |
|---|---:|---:|---:|---:|
| MISO | 3,828 | 562 | 2,143 | 1,123 |
| NYISO | 3,139 | 151 | 2,802 | 186 |
| CAISO | 2,278 | 251 | 1,762 | 265 |
| ISONE | 1,751 | 362 | 1,326 | 63 |
| **total** | **10,996** | **1,326** | **8,033** | **1,637** |

Three do not:

- **PJM** — requires a free `PJM_API_KEY`. Worth getting: PJM is the largest
  datacenter market that publishes a queue at all. Register at
  [apiportal.pjm.com](https://apiportal.pjm.com/), verify the email, then copy
  the Primary key from your profile's subscriptions into `.env`.
- **ERCOT** — 403s all scripted access. Publishes large-load only in aggregate.
- **SPP** — ops portal times out from here; may be transient.

Fetching is done through [`gridstatus`](https://github.com/gridstatus/gridstatus),
which normalises all seven ISOs onto one schema. There was no reason to write
another scraper.

## Why the naive number is wrong

`built / (built + withdrawn)` over everything gives **14.2%**. That is too low,
because a request filed in 2024 has not had time to be built and is counted as
though it had already failed. Censoring is being read as attrition.

So every rate here is computed per queue-year cohort, and a cohort is only
quoted once **≥90% of it has reached a terminal state**. On that basis the rate
is **21.4%** (n=5,436).

That number is biased the other way. 1,354 resolved records have no queue date
and fall out of every cohort — and they are 1,351 withdrawals to 3 builds
(mostly pre-2000 NYISO rows). If all of them belonged to quotable cohorts the
rate would be **17.2%**.

Hence the range. Neither end is quoted alone.

## What actually predicts attrition

Restricted to resolved requests in quotable cohorts (n=5,436). Wilson 95%
intervals, because several segments sit close to zero where the normal
approximation misbehaves.

**By size — the strongest and cleanest effect:**

| capacity | n | build rate | 95% CI |
|---|---:|---:|---|
| <20 MW | 1,024 | 28.8% | 26.1–31.7 |
| 20–100 MW | 1,639 | 19.0% | 17.2–21.0 |
| 100–300 MW | 1,654 | 23.9% | 21.9–26.0 |
| 300–1,000 MW | 680 | 12.6% | 10.4–15.4 |
| **≥1,000 MW** | **169** | **5.3%** | **2.8–9.8** |

Monotone above 100 MW, and the gigawatt bucket is an order of magnitude below
the small one. This is the commercially relevant cut: the AI datacenter power
story is *entirely* about gigawatt-scale interconnection, which is the size
class that historically almost never completes.

**By fuel, after normalising the ISOs' vocabularies:**

| fuel | n | build rate | 95% CI |
|---|---:|---:|---|
| gas | 625 | 33.1% | 29.5–36.9 |
| solar | 1,885 | 23.2% | 21.3–25.1 |
| wind | 861 | 19.5% | 17.0–22.3 |
| storage | 724 | 9.5% | 7.6–11.9 |

## Two bugs caught while building this

**1. Mixed date formats silently destroyed 7,400 of 9,640 dates.** The four
ISOs write queue dates four ways (`2003-11-18 08:00:00`, `1/14/2025`,
`2025-10-08T00:37:52+00:00`, `2008-01-30`). `pd.to_datetime` infers a single
format from the first non-null value and coerces everything that disagrees to
`NaT`. Parsed as one column, 84% of dates vanished — and the loss is
indistinguishable from ordinary missingness, so nothing downstream complained.
Caught only because `baserate.py` cross-tabulates date-missingness against
outcome before using cohorts. Dates are now parsed per ISO, with an assertion
that ≥98% of present values survive.

**2. Unnormalised fuel labels invented a finding.** The raw segment table
reported `Solar 32.1%` next to `Photovoltaic 13.0%` and `Wind 19.1%` next to
`Wnd 26.9%`. Same technologies, different ISO vocabularies — the gap was
measuring ISO composition. `fuel.py` maps them onto one set and prints the
fuel×ISO crosstab so the remaining confound stays visible.

## The portfolio question: do outcomes move together?

`src/frailty.py`. A probability per project answers "will this one be built".
It does not answer "how much will my forty projects deliver", and the gap
between those two questions is entirely about whether outcomes are independent.
They are not.

**Stage 1 — is there anything to model?** Given honest out-of-sample
probabilities, group build counts are compared with what independent Bernoulli
draws would produce. The comparison is against a *permutation* null — same
probabilities, same group sizes, group membership shuffled within queue year —
because the model is miscalibrated and miscalibration inflates raw dispersion
on its own. A chi-square table would have found "correlation" that was really
the model saying 65 and meaning 49.

| shared by | groups | dispersion | permuted null | inflation |
|---|---|---|---|---|
| fuel | 13 | 13.23 | 3.24 | **4.09x** |
| state | 27 | 5.64 | 2.15 | 2.62x |
| ISO study cycle | 59 | 7.41 | 3.93 | 1.88x |
| county | 132 | 2.14 | 1.19 | 1.80x |
| ISO | 4 | 15.41 | 8.77 | 1.76x |
| transmission owner | 22 | 4.32 | 2.51 | 1.72x |

All p < 0.00025, the floor at 4,000 permutations. Technology is the strongest
shared shock, ahead of geography — tariffs, cell prices and turbine lead times
hit every project of a type at once.

**Stage 2 — how big is the shock?** A random-intercept logit fitted by marginal
maximum likelihood, integrating the group effect out with Gauss-Hermite
quadrature. The study cycle carries tau = 1.06 on the log-odds scale, an ICC of
25.5%. Levels are fitted one at a time and therefore overlap, so the structure
is chosen by test rather than by taking the largest tau.

**Stage 3 — does it actually predict better?** Books of 40 are drawn from
held-out data and scored against each structure's predicted distribution. The
target for an 80% interval is 80%:

| book | independent | cycle+fuel+county |
|---|---|---|
| random | 78.7% | 89.0% |
| all one state | 74.5% | 88.1% |
| all one fuel | **62.6%** | 81.5% |

Independence is tolerable for a diversified book and dangerous for a
concentrated one — which is the realistic case for a developer or a lender. On
a single-fuel book its 80% interval contains the truth 62.6% of the time.

On the live book of 1,637 active requests, the frailty distribution is **4.3x
wider** than independence implies and its 1-in-10 bad case is **21.6 GW worse**.

### Read the shape, not the level

Two measured reasons the central estimate deserves less trust than the spread:

1. **Count calibration is not capacity calibration.** Probabilities calibrated
   so that each *project* is right overstate delivered *capacity* by +20.8%
   out-of-sample, because gigawatts sit in large projects and large projects
   fail more inside every size band. Re-fitting the calibration weighted by
   megawatts cuts the bias to +6.1% for 0.0007 of Brier. Adding a size band as
   a feature does not fix it — the bias is within bands, not between them.
2. **The live book is 68% MISO by capacity against 19% in training.** The
   headline therefore rests largely on one operator's record. 18% of the book's
   capacity sits in (iso, fuel) cells with fewer than 40 resolved historical
   requests; `support()` prints them.

The dispersion result is a ratio and survives both. The central estimate does
not, and is quoted with that attached.

## Known limitations

- **Fuel and ISO are not fully independent.** Solar, wind, gas and storage
  appear in all four ISOs, so the fuel table is not purely an ISO artifact, but
  it is not a controlled comparison either. The crosstab is printed; read it
  before quoting a fuel number.
- **CAISO's public queue report stops at 2023-03-02.** Recent CAISO activity is
  absent.
- **MISO's queue only goes back to 2015** (its queue was reset).
- **`Status` reflects an ISO's bookkeeping, not physical reality.** "Completed"
  means the interconnection agreement completed, not that electrons flowed.
- **Nothing here is a forecast.** These are historical base rates. No model has
  been fit and no out-of-sample claim is made.

## The archive — why this is the only part that compounds

The ISOs publish **current state only**. `Status`, `Capacity (MW)`,
`Proposed Completion Date`, `inService` and `studyPhase` are overwritten in
place on every refresh. When a 400 MW request is revised to 250, or a 2027
in-service date slips to 2029, **the previous value is not archived anywhere**
— not by the ISO, not by `gridstatus`, not by the aggregators.

So the revision history cannot be bought, back-scraped, or reconstructed. It
can only be accumulated from the first day someone starts. Every day without a
snapshot is a day of history that is gone permanently.

```
./venv/bin/python src/snapshot.py         # append-only, content-addressed
./venv/bin/python src/diff.py MISO        # change events between the last two
./venv/bin/python src/health.py           # days since each ISO last captured
```

**This runs automatically.** `scripts/daily_snapshot.sh` is driven by a launchd
agent (`~/Library/LaunchAgents/com.savabs.queue-snapshot.plist`) at 09:15 daily
and again at login — launchd runs a missed job once on the next wake rather
than skipping the day, and duplicate runs are free because snapshots are
content-addressed. The job commits `data/snapshots` only, so it can never
sweep up unfinished source edits, and it runs `src/health.py` every time
because a snapshot job that dies quietly is the one failure that cannot be
repaired later.

### Credentials

Copy `.env.example` to `.env` and fill it in. **Do not export keys in
`~/.zshrc`** — launchd starts jobs with a nearly empty environment and reads no
shell profile, so a key set that way works when you test it by hand and is
absent every night in the scheduled run, failing with a network-shaped error
that looks exactly like the source being down. `src/env.py` loads `.env` on the
Python side and the wrapper sources it on the shell side, so manual and
automated runs behave identically.

```
./venv/bin/python src/check_keys.py     # verify a key actually works
```

```
launchctl list | grep queue-snapshot          # is it loaded
tail -40 data/snapshots/run.log               # what it did last
launchctl unload -w ~/Library/LaunchAgents/com.savabs.queue-snapshot.plist   # stop it
```

Snapshots are hashed on content, so an unchanged refresh costs nothing and
still leaves a dated entry in `data/snapshots/index.jsonl`.

**`Queue ID` is not a primary key** and diffing on it corrupts the history
silently. ISONE reuses position `73` across eight different plants; NYISO
leaves it null on 1,350 historical rows and reuses `0031` for Astoria Phase 1
(Completed) and Phase 2 (Withdrawn). Identity is therefore a composite —
`Queue ID + Project Name + County + Interconnection Location + Queue Date` —
widened only until unique, and rows that still cannot be keyed are reported
and excluded from change tracking rather than guessed at (MISO 2, ISONE 8,
NYISO 1,350).

No watched field may appear in the identity key, or a revision would read as a
departure plus an arrival instead of a change. `src/diff.py` asserts this.

## Running it

```
./venv/bin/python src/fetch.py      # pull the queues (network)
./venv/bin/python src/build.py      # label outcomes -> data/queue_attrition.csv
./venv/bin/python src/baserate.py   # cohort-corrected base rates
./venv/bin/python src/segments.py   # by ISO, fuel, size, transmission owner
```

`src/build.py` keeps `Status`, `Withdrawn Date`, `Actual Completion Date` and
`Withdrawal Comment` out of the feature set — each is only knowable after the
outcome it would be used to predict — and asserts it.

## External check

LBNL's *Queued Up* reports that 75% of capacity requesting interconnection
2000–2020 had withdrawn by end-2025. This dataset gives 88.8% of MW withdrawn
across four ISOs on an uncorrected basis. The two are not directly comparable
(different ISO coverage, different windows, capacity vs count, and the 88.8%
carries the censoring bias described above) but they agree that the large
majority of queued capacity never gets built.
