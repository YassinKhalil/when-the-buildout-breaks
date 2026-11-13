"""Model F emulator.

The agent-based Model F (ai_bust_abm.py) steps weekly through thousands of agents and cannot be vectorised across
draws (about 0.9 s per draw). This module fits a regression emulator to a stratified set of real ABM runs
(quant/f_training.json, made by scripts/train_surrogate_f.py) and then draws 10,000 outcomes in milliseconds:

    y = f(shock, ABM parameters)  +  residual

where the mean f is a ridge regression (cubic in the shock plus parameter and shock x parameter terms; square-root scale
for dollar outputs) and the residual vector is resampled jointly from the training runs with the nearest shocks, so that
noise level, skew and the correlation between SPY drawdown, SMH proxy drawdown, credit loss and sovereign spend are kept.
Cross-validated skill is reported alongside every run. It is an approximation of Model F, not Model F itself.
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUTS = ["sp500_dd", "ai_dd", "credit_loss", "sov_spend"]
SQRT_OUTS = {"credit_loss", "sov_spend"}
KNN = 30


def _forward(name, y):
    return np.sqrt(np.clip(y, 0, None)) if name in SQRT_OUTS else y


def _inverse(name, z):
    return np.clip(z, 0, None) ** 2 if name in SQRT_OUTS else np.clip(z, 0.0, 0.95)


class FEmulator:
    def __init__(self, ridge: float = 1e-3):
        self.ridge = ridge

    # ---- features --------------------------------------------------------------------------------------------------
    def _X(self, shock, P):
        s = shock[:, None]
        Z = (P - self.p_mu) / self.p_sd
        return np.hstack([np.ones_like(s), s, s ** 2, s ** 3, Z, Z * s])

    def fit(self, rows: list[dict], priors: dict):
        self.pnames = list(priors)
        lo = np.array([priors[k][0] for k in self.pnames]); hi = np.array([priors[k][1] for k in self.pnames])
        self.priors = (lo, hi)
        self.p_mu, self.p_sd = (lo + hi) / 2, (hi - lo) / np.sqrt(12)
        shock = np.array([r["roi_shock"] for r in rows])
        P = np.array([[r[k] for k in self.pnames] for r in rows])
        X = self._X(shock, P)
        self.coef, self.res, self.shock_train = {}, {}, shock
        R = []
        for o in OUTS:
            z = _forward(o, np.array([r[o] for r in rows]))
            A = X.T @ X + self.ridge * np.eye(X.shape[1])
            self.coef[o] = np.linalg.solve(A, X.T @ z)
            R.append(z - X @ self.coef[o])
        self.resid = np.array(R).T                                  # (n, 4) joint residual vectors
        self.order = np.argsort(shock)
        return self

    # ---- sampling --------------------------------------------------------------------------------------------------
    def sample(self, shock: np.ndarray, rng: np.random.Generator) -> dict:
        n = shock.shape[0]
        lo, hi = self.priors
        P = rng.uniform(lo, hi, (n, len(lo)))
        X = self._X(shock, P)
        # nearest-shock residual pool: rank of each draw's shock among training shocks, then a random neighbour
        sorted_sh = self.shock_train[self.order]
        pos = np.clip(np.searchsorted(sorted_sh, shock), 0, len(sorted_sh) - 1)
        start = np.clip(pos - KNN // 2, 0, len(sorted_sh) - KNN)
        pick = self.order[start + rng.integers(0, KNN, n)]
        out = {}
        for j, o in enumerate(OUTS):
            out[o] = _inverse(o, X @ self.coef[o] + self.resid[pick, j])
        return out

    # ---- validation ------------------------------------------------------------------------------------------------
    @staticmethod
    def cross_validate(rows, priors, folds: int = 5, seed: int = 0) -> dict:
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(rows))
        parts = np.array_split(idx, folds)
        pred = {o: np.zeros(len(rows)) for o in OUTS}
        samp = {o: np.zeros(len(rows)) for o in OUTS}
        for k in range(folds):
            test = parts[k]
            train = np.concatenate([parts[j] for j in range(folds) if j != k])
            m = FEmulator().fit([rows[i] for i in train], priors)
            sh = np.array([rows[i]["roi_shock"] for i in test])
            P = np.array([[rows[i][p] for p in m.pnames] for i in test])
            X = m._X(sh, P)
            drawn = m.sample(sh, np.random.default_rng(seed + k))
            for o in OUTS:
                pred[o][test] = _inverse(o, X @ m.coef[o])
                samp[o][test] = drawn[o]
        rep = {}
        for o in OUTS:
            y = np.array([r[o] for r in rows])
            ss = ((y - pred[o]) ** 2).sum(); tot = ((y - y.mean()) ** 2).sum()
            rep[o] = {"r2_heldout": round(float(1 - ss / tot), 3), "mae": round(float(np.abs(y - pred[o]).mean()), 4),
                      "mean_real": round(float(y.mean()), 4), "mean_emulated": round(float(samp[o].mean()), 4),
                      "p95_real": round(float(np.quantile(y, .95)), 4), "p95_emulated": round(float(np.quantile(samp[o], .95)), 4)}
        return rep


def load(path: str | None = None) -> tuple["FEmulator", dict]:
    d = json.load(open(path or os.path.join(HERE, "f_training.json")))
    em = FEmulator().fit(d["rows"], d["param_priors"])
    meta = {"n_training_runs": d["n"], "abm_sha256_16": d["abm_sha256_16"],
            "validation_5fold": FEmulator.cross_validate(d["rows"], d["param_priors"])}
    return em, meta
