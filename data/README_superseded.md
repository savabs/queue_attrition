# predictions_superseded_2026-09-02.csv

The first version of the prediction ledger, kept because deleting it would make
the correction unverifiable.

It was written on 2026-09-02 at 06:50 UTC and replaced the same day, before any
entry had resolved and before it was published anywhere. Every one of its 1,636
rows was `open`. Two defects in how the deadline was set:

* 62 rows carried a `resolves_by` already in the past -- earliest 2002 --
  because the field was taken raw from the ISO's "Proposed Completion Date",
  which a stalled project keeps long after it has missed it. A prediction with
  an elapsed deadline cannot be falsified, so those 62 were not predictions.
* 63 rows were in `M/D/YYYY` among 1,573 in ISO-8601, because the value was
  passed through as a string. Ambiguous to parse and wrong to sort.

Fixed in `src/predict_active.py::resolves_by`, which parses per row and floors
every deadline two years past the date the call was made.

This is a rewrite of a ledger that is supposed to be append-only. It is
defensible exactly once, on the day of creation, with nothing resolved and
nothing published. Once an outcome is written, the ledger is frozen and a
mistake gets a new model ID, not a new file.
