"""The prediction registry. Domain-agnostic, append-only, self-scoring.

One engine for anything that resolves on its own: an interconnection request,
an IPO listing, a loan. You log a probability BEFORE the outcome exists, the
outcome arrives later, and the registry scores you whether or not you want it
to.

Three properties, and they are the whole point:

1. **Append-only.** A prediction is never edited or deleted. Rewriting a call
   after the fact is the single thing that turns a track record into a lie, so
   the writer refuses rather than trusting discipline.

2. **Predictions carry their resolution rule.** `resolves_by` and
   `outcome_source` are recorded at prediction time, so "when does this count
   and who decides" is fixed before the answer is known rather than argued
   about afterwards.

3. **Scoring is against the base rate, not against zero.** A model that cannot
   beat quoting the historical average has produced nothing, however good it
   looks in isolation.

The registry is a CSV on purpose. Committed to git, it is timestamped by a
third party, and that is what makes an entry un-backdatable.
"""
import csv
import os
from datetime import datetime, timezone

FIELDS = [
    # written at prediction time, never touched again
    "predicted_at", "domain", "entity_id", "entity_name",
    "p", "model", "features_json", "thesis",
    "resolves_by", "outcome_source",
    # written once, when reality arrives
    "outcome", "resolved_at", "resolution_note",
]

OPEN, HIT, MISS = "open", 1, 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(path: str, *, domain: str, entity_id: str, p: float,
        resolves_by: str, outcome_source: str, entity_name: str = "",
        model: str = "", features_json: str = "", thesis: str = "") -> dict:
    """Record one prediction. Refuses to overwrite an existing entity_id."""
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be a probability, got {p}")
    if not resolves_by or not outcome_source:
        raise ValueError(
            "resolves_by and outcome_source are required: a prediction with no "
            "stated resolution rule cannot be scored honestly later"
        )

    existing = {r["entity_id"] for r in read(path) if r["domain"] == domain}
    if entity_id in existing:
        raise ValueError(
            f"{domain}/{entity_id} already predicted. The registry is "
            "append-only; a second opinion is a new entity_id, not an edit."
        )

    row = {f: "" for f in FIELDS}
    row.update(predicted_at=_now(), domain=domain, entity_id=str(entity_id),
               entity_name=entity_name, p=f"{p:.6f}", model=model,
               features_json=features_json, thesis=thesis,
               resolves_by=resolves_by, outcome_source=outcome_source,
               outcome=OPEN)
    _append(path, row)
    return row


def resolve(path: str, *, domain: str, entity_id: str, outcome: int,
            note: str = "") -> None:
    """Fill in what actually happened. Only ever open -> resolved, once."""
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    rows = read(path)
    hit = [r for r in rows if r["domain"] == domain and r["entity_id"] == str(entity_id)]
    if not hit:
        raise ValueError(f"{domain}/{entity_id} was never predicted")
    if hit[0]["outcome"] != OPEN:
        raise ValueError(
            f"{domain}/{entity_id} already resolved as {hit[0]['outcome']}. "
            "Outcomes are written once."
        )
    for r in rows:
        if r["domain"] == domain and r["entity_id"] == str(entity_id):
            r.update(outcome=str(outcome), resolved_at=_now(), resolution_note=note)
    _rewrite(path, rows)


def read(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _append(path: str, row: dict) -> None:
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def _rewrite(path: str, rows: list) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def score(path: str, domain: str = None) -> dict:
    """Grade the record. Resolved entries only -- open ones are not failures.

    Reported against the base rate of the resolved set, because beating "quote
    the average to everyone" is the only bar that means anything. Calibration
    is reported per bucket, since a good average can hide a model that is
    confidently wrong at both ends.
    """
    rows = [r for r in read(path) if r["outcome"] in ("0", "1")]
    if domain:
        rows = [r for r in rows if r["domain"] == domain]
    if not rows:
        return {"n": 0, "open": len([r for r in read(path) if r["outcome"] == OPEN])}

    ps = [float(r["p"]) for r in rows]
    ys = [int(r["outcome"]) for r in rows]
    n = len(rows)
    base = sum(ys) / n

    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    brier_base = sum((base - y) ** 2 for y in ys) / n
    skill = 1 - brier / brier_base if brier_base else float("nan")

    edges = [0, .05, .1, .2, .3, .5, .7, 1.01]
    buckets = []
    for lo, hi in zip(edges, edges[1:]):
        sel = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if sel:
            buckets.append({
                "range": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(sel),
                "predicted": sum(p for p, _ in sel) / len(sel),
                "actual": sum(y for _, y in sel) / len(sel),
            })

    return {"n": n, "open": len([r for r in read(path) if r["outcome"] == OPEN]),
            "base_rate": base, "mean_prediction": sum(ps) / n,
            "brier": brier, "brier_base": brier_base, "skill": skill,
            "buckets": buckets}


def report(path: str, domain: str = None) -> str:
    s = score(path, domain)
    if not s["n"]:
        return (f"no resolved predictions yet ({s['open']} open).\n"
                "The record starts when the first one resolves, not when it is logged.")
    out = [
        f"resolved: {s['n']}    still open: {s['open']}",
        f"base rate: {s['base_rate']:.1%}    mean prediction: {s['mean_prediction']:.1%}",
        f"Brier: {s['brier']:.4f}   vs base rate {s['brier_base']:.4f}   "
        f"skill {s['skill']:+.2%}",
    ]
    if s["n"] < 20:
        out.append(f"  ** n={s['n']}: too few to conclude anything. Keep logging. **")
    out.append("\ncalibration:")
    out.append(f"  {'range':<12}{'n':>5}{'said':>9}{'happened':>10}")
    for b in s["buckets"]:
        out.append(f"  {b['range']:<12}{b['n']:>5}{b['predicted']:>9.1%}{b['actual']:>10.1%}")
    return "\n".join(out)
