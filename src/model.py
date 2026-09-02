"""P(built) with walk-forward validation and a calibration curve.

The product claim is not "this predicts winners". It is: **when this says 20%,
it happens about 20% of the time.** That claim is checkable, it resolves on its
own, and it is worth the same to someone long the trade as to someone short it.

Two disciplines make the number mean anything:

1. Walk-forward by queue vintage. Train on cohorts up to year Y, predict Y+1.
   Random k-fold would let a 2019 project learn from 2021 outcomes, which is
   not a situation anyone is ever in.

2. Score against the base rate, not against zero. A model that cannot beat
   "quote the historical rate to everyone" has produced nothing, however good
   its AUC looks.

Only features knowable when the request enters the queue are used. Everything
resolved after that -- status, withdrawal date, completion date -- is excluded
by build.py and asserted there.
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baserate import cohorts, load  # noqa: E402
from fuel import normalise  # noqa: E402

CAT = ["iso", "fuel", "to_top"]
NUM = ["log_mw", "queue_year"]
MIN_TRAIN = 300


def frame() -> pd.DataFrame:
    df = load()
    c = cohorts(df)
    mature = set(c.index[c["quotable"]])

    d = df[df["outcome"].isin(["built", "withdrawn"])].copy()
    d = d[d["queue_year"].isin(mature)]
    d["y"] = (d["outcome"] == "built").astype(int)
    d["fuel"] = d["Generation Type"].map(normalise)
    d["log_mw"] = np.log1p(d["capacity_mw"].clip(lower=0))
    # Rare transmission owners become one bucket: a TO seen 3 times cannot
    # support its own coefficient, and letting it have one is how a model
    # memorises the training set.
    to = d["Transmission Owner"].astype(str).str.strip().str.upper()
    common = to.value_counts()
    d["to_top"] = to.where(to.map(common) >= 40, "OTHER")
    d["log_mw"] = d["log_mw"].fillna(d["log_mw"].median())
    return d.dropna(subset=["queue_year"])


def pipe() -> Pipeline:
    return Pipeline([
        ("prep", ColumnTransformer([
            ("c", OneHotEncoder(handle_unknown="ignore", min_frequency=10), CAT),
            ("n", StandardScaler(), NUM),
        ])),
        ("clf", LogisticRegression(max_iter=2000, C=1.0)),
    ])


def walk_forward(d: pd.DataFrame) -> pd.DataFrame:
    years = sorted(d["queue_year"].unique())
    rows = []
    for y in years:
        tr, te = d[d["queue_year"] < y], d[d["queue_year"] == y]
        if len(tr) < MIN_TRAIN or len(te) < 25 or tr["y"].nunique() < 2:
            continue
        # Raw logistic scores are not calibrated -- measured below, they read
        # 65% where the truth is 49%. Isotonic regression fixes the mapping,
        # and is fitted with internal CV on the TRAINING years only: calibrating
        # on the test year would be fitting the answer.
        base_clf = CalibratedClassifierCV(pipe(), method="isotonic", cv=5)
        m = base_clf.fit(tr[CAT + NUM], tr["y"])
        p = m.predict_proba(te[CAT + NUM])[:, 1]

        raw = pipe().fit(tr[CAT + NUM], tr["y"]).predict_proba(te[CAT + NUM])[:, 1]
        base = tr["y"].mean()  # what you'd say knowing only history
        rows.append({
            "test_year": int(y), "n_train": len(tr), "n_test": len(te),
            "actual": te["y"].mean(), "base_rate": base,
            "brier": brier_score_loss(te["y"], p),
            "brier_base": brier_score_loss(te["y"], np.full(len(te), base)),
            "auc": roc_auc_score(te["y"], p) if te["y"].nunique() > 1 else np.nan,
        })
        rows[-1]["brier_raw"] = brier_score_loss(te["y"], raw)
        rows[-1]["_preds"] = te[["y"]].assign(p=p, raw=raw)
    return pd.DataFrame(rows)


def reliability(preds: pd.DataFrame, bins=(0, .05, .10, .15, .20, .30, .50, 1.0)):
    b = pd.cut(preds["p"], bins=list(bins), include_lowest=True)
    g = preds.groupby(b, observed=True).agg(
        n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    z = 1.96
    p, n = g["actual"], g["n"]
    den = 1 + z**2 / n
    ctr = (p + z**2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    g["lo95"], g["hi95"] = (ctr - half).clip(0, 1), (ctr + half).clip(0, 1)
    g["covers"] = (g["predicted"] >= g["lo95"]) & (g["predicted"] <= g["hi95"])
    return g


if __name__ == "__main__":
    d = frame()
    print(f"resolved requests in mature cohorts: {len(d):,}  "
          f"built={d['y'].sum():,} ({d['y'].mean():.1%})")

    res = walk_forward(d)
    if res.empty:
        raise SystemExit("not enough history to walk forward")

    print("\n=== WALK-FORWARD (train on everything before, predict that year) ===")
    show = res.drop(columns=["_preds"])
    print(show.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    tot_b = (res["brier"] * res["n_test"]).sum() / res["n_test"].sum()
    tot_0 = (res["brier_base"] * res["n_test"]).sum() / res["n_test"].sum()
    print(f"\n  Brier (model)     : {tot_b:.4f}")
    print(f"  Brier (base rate) : {tot_0:.4f}")
    print(f"  skill score       : {1 - tot_b / tot_0:+.3%}   "
          f"({'beats' if tot_b < tot_0 else 'LOSES TO'} quoting the base rate)")

    allp = pd.concat(res["_preds"].tolist(), ignore_index=True)
    for col, label in (("raw", "BEFORE calibration"), ("p", "AFTER isotonic")):
        r = reliability(allp[["y"]].assign(p=allp[col]))
        print(f"\n=== CALIBRATION, {label} (out-of-sample, pooled) ===")
        print("  'covers' = predicted rate falls inside the actual 95% interval")
        print(r.to_string(float_format=lambda x: f"{x:.3f}"))
        print(f"  bins covering: {int(r['covers'].sum())}/{len(r)}")
