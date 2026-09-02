"""Do interconnection outcomes co-move, and if so what does that do to a book?

A portfolio number is only as good as its independence assumption. If you hold
40 projects each 20% likely to be built and treat them as independent coin
flips, the arithmetic says you will get 8 give or take 2.5, and the chance of
getting 2 or fewer is about 1%. If instead those projects share an ISO study
cycle, a transmission owner's capex plan, an equipment supplier and a state
policy regime, then one bad shock moves all of them at once, the distribution
grows a tail, and that 1% can be an order of magnitude off.

That is the claim a shared-frailty model exists to make. It is also a claim
that can be wrong, so this module measures it before fitting anything:

  Stage 1 (`dispersion`)  Given honest out-of-sample probabilities, do outcomes
                          within a group vary MORE than independent Bernoulli
                          draws would? Tested against a permutation null that
                          keeps every predicted probability and every group
                          size and destroys only the group *membership*. The
                          model is known to be miscalibrated -- it says 65 and
                          means 49 -- and miscalibration inflates a raw
                          chi-square. Permutation is immune to that, because
                          the null shares the same miscalibration.

  Stage 2 (`fit`)         Only if stage 1 finds something: a random-intercept
                          logistic model fitted by marginal maximum likelihood,
                          integrating the group effect out with Gauss-Hermite
                          quadrature. Returns tau, the frailty standard
                          deviation, on the log-odds scale.

  Stage 3 (`simulate`)    The product: draw a shock per group, then outcomes
                          conditional on it, and report the distribution of
                          delivered capacity rather than its mean.

If stage 1 comes back empty the honest answer is that independence is fine
here, and stages 2 and 3 should not be quoted. That verdict is printed either
way.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, roots_hermitenorm
from sklearn.calibration import CalibratedClassifierCV

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import CAT, MIN_TRAIN, NUM, frame, pipe  # noqa: E402

SEED = 20260902
N_PERM = 4000
# A group needs enough projects for its build count to carry information about
# a shared shock. Below this a group is a coin flip and adds only noise.
MIN_GROUP = 8


def oos_predictions(d: pd.DataFrame) -> pd.DataFrame:
    """Walk-forward probabilities, keeping the columns needed to group them.

    model.py throws the identifiers away because it only ever needed y and p.
    Everything here is about which projects share what, so they are kept.
    """
    keep = ["iso", "to_top", "fuel", "queue_year", "County", "State",
            "capacity_mw", "y"]
    keep = [c for c in keep if c in d.columns]
    out = []
    for yr in sorted(d["queue_year"].unique()):
        tr, te = d[d["queue_year"] < yr], d[d["queue_year"] == yr]
        if len(tr) < MIN_TRAIN or len(te) < 25 or tr["y"].nunique() < 2:
            continue
        m = CalibratedClassifierCV(pipe(), method="isotonic", cv=5)
        m.fit(tr[CAT + NUM], tr["y"])
        p = m.predict_proba(te[CAT + NUM])[:, 1]
        out.append(te[keep].assign(p=p))
    res = pd.concat(out, ignore_index=True)
    res["cycle"] = res["iso"].astype(str) + ":" + res["queue_year"].astype(int).astype(str)
    return res


def _stat(y: np.ndarray, p: np.ndarray, g: np.ndarray, sizes: dict) -> float:
    """Pearson dispersion of group build counts around their expected counts.

    Under conditional independence each group's count has variance sum p(1-p),
    so this sums to roughly the number of groups. Above that means outcomes
    inside a group are moving together.
    """
    df = pd.DataFrame({"y": y, "p": p, "g": g})
    a = df.groupby("g").agg(obs=("y", "sum"), exp=("p", "sum"),
                            var=("p", lambda s: (s * (1 - s)).sum()),
                            n=("y", "size"))
    a = a[a["n"] >= MIN_GROUP]
    a = a[a["var"] > 0]
    if a.empty:
        return np.nan
    return float(((a["obs"] - a["exp"]) ** 2 / a["var"]).sum() / len(a))


def dispersion(preds: pd.DataFrame, by: str, n_perm: int = N_PERM,
               seed: int = SEED) -> dict:
    """Is there clustering in `by` beyond what the probabilities already say?

    The permutation shuffles group labels within each queue year. Within-year
    is deliberate: a whole cohort being unusually good or bad is a real effect
    but it is not evidence that ISOs or transmission owners cluster, and
    permuting across years would let cohort drift pose as group structure.
    """
    rng = np.random.default_rng(seed)
    y = preds["y"].to_numpy()
    p = preds["p"].to_numpy()
    g = preds[by].astype(str).to_numpy()
    year = preds["queue_year"].to_numpy()

    sizes = pd.Series(g).value_counts().to_dict()
    obs = _stat(y, p, g, sizes)

    # Index blocks to permute within.
    blocks = [np.flatnonzero(year == u) for u in np.unique(year)]
    null = np.empty(n_perm)
    gp = g.copy()
    for k in range(n_perm):
        for idx in blocks:
            gp[idx] = g[rng.permutation(idx)]
        null[k] = _stat(y, p, gp, sizes)

    null = null[~np.isnan(null)]
    pval = (1 + (null >= obs).sum()) / (1 + len(null))
    n_groups = int((preds.groupby(by).size() >= MIN_GROUP).sum())
    return {"by": by, "groups": n_groups, "stat": obs,
            "null_mean": float(null.mean()), "null_p95": float(np.quantile(null, .95)),
            "p_value": float(pval)}


# ---------------------------------------------------------------- stage 2

_GH_NODES, _GH_WEIGHTS = roots_hermitenorm(24)
_GH_WEIGHTS = _GH_WEIGHTS / _GH_WEIGHTS.sum()


def _neg_loglik(tau: float, eta: np.ndarray, y: np.ndarray,
                codes: np.ndarray, n_groups: int) -> float:
    """Marginal likelihood of a random-intercept logit, group effect integrated out.

    For each group, P(data) = integral over the shock u ~ N(0, tau^2) of the
    product of Bernoulli terms. Gauss-Hermite turns that integral into a
    weighted sum over 24 nodes. Working in log space per group, because the
    per-group products underflow otherwise.
    """
    if tau <= 0:
        tau = 1e-9
    # log P(y_i | u) for every observation at every quadrature node
    lin = eta[:, None] + tau * _GH_NODES[None, :]
    ll = np.where(y[:, None] == 1, -np.logaddexp(0, -lin), -np.logaddexp(0, lin))
    # sum within group
    acc = np.zeros((n_groups, len(_GH_NODES)))
    np.add.at(acc, codes, ll)
    acc += np.log(_GH_WEIGHTS)[None, :]
    m = acc.max(axis=1, keepdims=True)
    per_group = (m[:, 0] + np.log(np.exp(acc - m).sum(axis=1)))
    return -float(per_group.sum())


def fit_tau(preds: pd.DataFrame, by: str) -> dict:
    """Frailty SD on the log-odds scale, holding the fitted probabilities fixed.

    The fixed effects come from the walk-forward model that is already
    validated; this asks only how much variance is left that groups explain.
    Estimating both together on the same rows would let the shared effect
    absorb ordinary lack of fit.
    """
    p = preds["p"].to_numpy().clip(1e-6, 1 - 1e-6)
    eta = np.log(p / (1 - p))
    y = preds["y"].to_numpy().astype(float)
    codes, uniq = pd.factorize(preds[by].astype(str))
    n_groups = len(uniq)

    r = minimize_scalar(_neg_loglik, bounds=(1e-6, 4.0), method="bounded",
                        args=(eta, y, codes, n_groups),
                        options={"xatol": 1e-4})
    tau = float(r.x)
    ll_tau = -r.fun
    ll_0 = -_neg_loglik(1e-9, eta, y, codes, n_groups)
    # ICC on the latent logistic scale: shared variance over total.
    icc = tau**2 / (tau**2 + np.pi**2 / 3)
    return {"by": by, "tau": tau, "icc": icc, "groups": n_groups,
            "loglik_gain": ll_tau - ll_0, "lrt_stat": 2 * (ll_tau - ll_0)}


# ---------------------------------------------------------------- stage 3

# Candidate frailty structures. Marginal taus overlap -- a book concentrated in
# one state is concentrated in few counties too -- so which combination to use
# is decided by out-of-sample portfolio coverage below, not by picking the
# largest tau.
STRUCTURES = {
    "independent": [],
    "cycle": ["cycle"],
    "cycle+fuel": ["cycle", "fuel"],
    "cycle+fuel+state": ["cycle", "fuel", "State"],
    "cycle+fuel+county": ["cycle", "fuel", "County"],
}


def simulate(book: pd.DataFrame, taus: dict, n_sims: int = 20000,
             seed: int = SEED) -> np.ndarray:
    """Delivered capacity across `n_sims` possible futures for one book.

    One shock is drawn per group per simulation, not per project: that is the
    whole point. Every project in the same study cycle moves with the same
    draw, so a bad cycle takes the whole cycle down together instead of
    averaging out.
    """
    rng = np.random.default_rng(seed)
    p = book["p"].to_numpy().clip(1e-6, 1 - 1e-6)
    eta0 = np.log(p / (1 - p))
    mw = book["capacity_mw"].fillna(0).to_numpy()
    n = len(p)

    levels = [(lv, tau, *pd.factorize(book[lv].astype(str))[::1])
              for lv, tau in taus.items()
              if tau > 0 and lv in book.columns]
    levels = [(lv, tau, pd.factorize(book[lv].astype(str))[0],
               book[lv].astype(str).nunique())
              for lv, tau, *_ in levels]

    # Adding a mean-zero shock on the log-odds scale lowers the average
    # probability (the logit is concave above the midpoint), so a raw frailty
    # would quietly shift the whole book pessimistic. The scale factor restores
    # the marginal mean to the calibrated p that was actually validated. It is
    # estimated once on a pilot batch rather than per chunk, so every chunk is
    # drawn from the same distribution.
    def _q(m: int, r) -> np.ndarray:
        eta = np.tile(eta0, (m, 1))
        for _, tau, codes, k in levels:
            eta += r.normal(0.0, tau, size=(m, k))[:, codes]
        return expit(eta)

    pilot = _q(min(2000, n_sims), np.random.default_rng(seed + 1))
    scale = p.sum() / pilot.mean(axis=0).sum()
    del pilot

    # Chunked because the full array is n_sims x n_projects: at 40,000 draws
    # over a 1,600-project book that is half a gigabyte per intermediate, and
    # there are three of them.
    chunk = max(1, min(n_sims, int(4e6 // max(n, 1))))
    mws, cnts = [], []
    done = 0
    while done < n_sims:
        m = min(chunk, n_sims - done)
        q = (_q(m, rng) * scale).clip(0, 1)
        draws = rng.random((m, n)) < q
        mws.append(draws @ mw)
        cnts.append(draws.sum(axis=1))
        done += m
    return np.concatenate(mws), np.concatenate(cnts)


def _pit(sample: np.ndarray, observed: float, rng) -> float:
    """Randomised PIT, because a count distribution is discrete.

    A correctly specified model gives PIT values uniform on [0,1]. Too many
    near 0 and 1 means the predicted spread is too narrow -- which is exactly
    the failure independence makes.
    """
    lo = (sample < observed).mean()
    hi = (sample <= observed).mean()
    return lo + rng.random() * (hi - lo)


def validate(preds: pd.DataFrame, taus_by_level: dict, book_size: int = 40,
             n_books: int = 400, concentrate: str | None = None,
             n_sims: int = 4000, seed: int = SEED) -> pd.DataFrame:
    """Out-of-sample test: do real books land inside the predicted interval?

    Books are drawn from held-out data and scored against what each structure
    predicted for them. `concentrate` builds the book inside a single group --
    one state, one fuel -- which is the realistic case for a developer or a
    lender and the case where independence fails worst.
    """
    rng = np.random.default_rng(seed)
    rows = []
    pool = preds.dropna(subset=["capacity_mw"])
    for name, levels in STRUCTURES.items():
        taus = {lv: taus_by_level[lv] for lv in levels}
        pits, inside80, inside50 = [], [], []
        for b in range(n_books):
            if concentrate:
                grp = pool[concentrate].dropna().sample(1, random_state=int(rng.integers(1e9))).iloc[0]
                cand = pool[pool[concentrate] == grp]
                if len(cand) < book_size:
                    continue
            else:
                cand = pool
            book = cand.sample(book_size, random_state=int(rng.integers(1e9)))
            _, counts = simulate(book, taus, n_sims=n_sims,
                                 seed=int(rng.integers(1e9)))
            obs = int(book["y"].sum())
            pits.append(_pit(counts, obs, rng))
            lo, hi = np.quantile(counts, [.10, .90])
            inside80.append(lo <= obs <= hi)
            lo, hi = np.quantile(counts, [.25, .75])
            inside50.append(lo <= obs <= hi)
        pits = np.array(pits)
        rows.append({
            "structure": name, "books": len(pits),
            "cover80": float(np.mean(inside80)), "cover50": float(np.mean(inside50)),
            # Uniformity of the PIT: 0 is perfect, bigger is worse.
            "pit_ks": float(np.max(np.abs(np.sort(pits) -
                            (np.arange(1, len(pits) + 1) - .5) / len(pits)))),
        })
    return pd.DataFrame(rows)


# Chosen by the validation above rather than by which tau was largest: it holds
# 80% coverage closest to 80% across diversified AND concentrated books, and has
# the most uniform PIT in two of the three tests. cycle+fuel+state was better on
# one test and clearly over-covered (94.9%) on another, which is its own kind of
# wrong -- an interval too wide is a number nobody can act on.
CHOSEN = ["cycle", "fuel", "County"]


def portfolio(book: pd.DataFrame, taus: dict, n_sims: int = 40000,
              seed: int = SEED) -> dict:
    """The answer the independence arithmetic cannot give: a distribution."""
    mw_ind, n_ind = simulate(book, {}, n_sims=n_sims, seed=seed)
    mw_frl, n_frl = simulate(book, taus, n_sims=n_sims, seed=seed)
    qs = [.05, .10, .25, .50, .75, .90, .95]
    return {
        "n_projects": len(book),
        "mw_queued": float(book["capacity_mw"].fillna(0).sum()),
        "expected_mw": float(mw_frl.mean()),
        "independent": {f"p{int(q*100)}": float(np.quantile(mw_ind, q)) for q in qs},
        "frailty": {f"p{int(q*100)}": float(np.quantile(mw_frl, q)) for q in qs},
        "sd_ratio": float(mw_frl.std() / mw_ind.std()),
        "p10_gap_mw": float(np.quantile(mw_ind, .10) - np.quantile(mw_frl, .10)),
    }


def _live_book(weight_by_capacity: bool = True) -> pd.DataFrame:
    """Every request still active, with probabilities calibrated for the question.

    Two different products need two different calibrations, and conflating them
    was a real error here:

      "Will THIS project be built?"     -> calibrate on counts. Every project
                                           weighs the same. This is the ledger,
                                           frozen under model id `logistic-v1`
                                           with raw uncalibrated scores.

      "How many GW will this BOOK deliver?" -> calibrate weighted by megawatts.
                                           Count calibration is dominated by
                                           small projects, which are numerous,
                                           while the gigawatts sit in the large
                                           ones -- which fail more, inside every
                                           size band. Measured out-of-sample,
                                           count-calibrated probabilities
                                           overstate delivered capacity by
                                           +20.8%; weighting the calibration by
                                           MW cuts that to +6.1% for 0.0007 of
                                           Brier.

    sklearn passes sample_weight to the calibration step only, not to the base
    estimator, and warns about it. That is precisely the intent here -- the
    ranking model is unchanged, only the mapping from score to probability is
    re-fitted against the quantity being reported.
    """
    from predict_active import active_rows
    train = frame()
    m = CalibratedClassifierCV(pipe(), method="isotonic", cv=5)
    if weight_by_capacity:
        w = train["capacity_mw"].fillna(0).clip(lower=1.0)
        m.fit(train[CAT + NUM], train["y"], sample_weight=w)
    else:
        m.fit(train[CAT + NUM], train["y"])
    a = active_rows()
    a = a.assign(p=m.predict_proba(a[CAT + NUM])[:, 1])
    a["cycle"] = a["iso"].astype(str) + ":" + a["queue_year"].astype(int).astype(str)
    return a


MIN_CELL = 40


def support(book: pd.DataFrame, train: pd.DataFrame) -> pd.DataFrame:
    """Where does this book rely on history that barely exists?

    The live book is 68% MISO by capacity while the training data is 19% MISO.
    That is not automatically wrong -- MISO really does build a larger share of
    what it queues -- but it means the headline leans almost entirely on one
    operator's record. A book weighted into (iso, fuel) cells with thin history
    deserves a warning next to its number rather than a footnote below it.
    """
    tr = train.assign(mw=train["capacity_mw"].fillna(0))
    bk = book.assign(mw=book["capacity_mw"].fillna(0))
    h = tr.groupby(["iso", "fuel"]).apply(
        lambda d: pd.Series({"hist_n": len(d),
                             "hist_rate": (d["y"] * d["mw"]).sum() / max(d["mw"].sum(), 1)}),
        include_groups=False)
    l = bk.groupby(["iso", "fuel"]).apply(
        lambda d: pd.Series({"GW": d["mw"].sum() / 1000,
                             "pred_rate": (d["p"] * d["mw"]).sum() / max(d["mw"].sum(), 1)}),
        include_groups=False)
    out = l.join(h, how="left").fillna({"hist_n": 0})
    out["thin"] = out["hist_n"] < MIN_CELL
    return out.sort_values("GW", ascending=False)


def _fmt(d: dict) -> str:
    return "  ".join(f"{k}={v/1000:,.1f}" for k, v in d.items())


if __name__ == "__main__":
    d = frame()
    pr = oos_predictions(d)
    print(f"out-of-sample predictions: {len(pr):,}  "
          f"mean p {pr['p'].mean():.3f} vs actual {pr['y'].mean():.3f}\n")

    print("=" * 74)
    print("STAGE 1 -- is there any clustering to model?")
    print("=" * 74)
    print("stat 1.0 would mean independence. The null is NOT 1.0 because the")
    print("model is miscalibrated, and miscalibration inflates dispersion on its")
    print("own -- so the comparison is against permuted group labels, not a table.\n")
    disp = pd.DataFrame([dispersion(pr, c) for c in
                         ["fuel", "State", "cycle", "County", "iso", "to_top"]])
    disp["inflation"] = disp["stat"] / disp["null_mean"]
    print(disp.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    if (disp["p_value"] > 0.05).all():
        raise SystemExit("\nNo clustering found. Independence is adequate; "
                         "do not quote a frailty model.")

    print("\n" + "=" * 74)
    print("STAGE 2 -- how big is the shared shock?")
    print("=" * 74)
    levels = ["cycle", "County", "State", "fuel", "to_top", "iso"]
    taus_all = {c: fit_tau(pr, c) for c in levels}
    print(pd.DataFrame(taus_all.values()).sort_values("tau", ascending=False)
          .to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\ntau is on the log-odds scale; icc is the share of latent variance")
    print("that is shared rather than idiosyncratic. Fitted one level at a time,")
    print("so they overlap -- which is why the structure is chosen by test, next.")

    taus = {c: taus_all[c]["tau"] for c in CHOSEN}

    print("\n" + "=" * 74)
    print("STAGE 3 -- the live book")
    print("=" * 74)
    book = _live_book()
    r = portfolio(book, taus)
    print(f"{r['n_projects']:,} active requests, {r['mw_queued']/1000:,.0f} GW queued")
    print(f"expected delivery {r['expected_mw']/1000:,.1f} GW\n")
    print("  GW delivered, by percentile")
    print(f"    independence  {_fmt(r['independent'])}")
    print(f"    with frailty  {_fmt(r['frailty'])}")
    print(f"\n  spread is {r['sd_ratio']:.2f}x wider once shocks are shared")
    print(f"  the 1-in-10 bad case is {r['p10_gap_mw']/1000:,.1f} GW worse "
          "than independence implies")

    print("\n" + "=" * 74)
    print("WHAT THIS NUMBER LEANS ON")
    print("=" * 74)
    sup = support(book, d)
    thin_gw = sup.loc[sup["thin"], "GW"].sum()
    print(sup.head(10).to_string(float_format=lambda x: f"{x:.3f}"))
    print(f"\n  {thin_gw:.0f} GW of {r['mw_queued']/1000:.0f} GW "
          f"({100*thin_gw/(r['mw_queued']/1000):.0f}%) sits in (iso, fuel) cells with "
          f"fewer than {MIN_CELL} resolved historical requests.")
    print("\n  Read the SHAPE, not the LEVEL. The dispersion result is a relative")
    print("  quantity and survives the composition problem; the central estimate")
    print("  does not. Measured out-of-sample, capacity-calibrated probabilities")
    print("  still overstate delivered GW by about 6%, and this book is 68% MISO")
    print("  by capacity against 19% in training, so the level rests on one")
    print("  operator's record being right.")
