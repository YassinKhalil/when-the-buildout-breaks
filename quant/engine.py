"""10,000-draw Monte Carlo for Model D (exact, vectorised) and Model F (emulator), parallelised with joblib."""
from __future__ import annotations

import time

import numpy as np
from joblib import Parallel, delayed

from quant import contagion_vec as V
from quant import surrogate_f

SMH_BETA_TO_AI_INDEX = 1.0   # SMH drawdown = this x Model F's AI-index drawdown (ASSUMED: the AI index is the closest model analogue)


def _d_chunk(seed_seq, n, sf, p_bust):
    rng = np.random.default_rng(seed_seq)
    shock = V.draw_shocks(sf, p_bust, rng, n)
    out = V.simulate_chunk(shock, V.draw_parameters(shock, rng))
    out["shock"] = shock
    return out


def run_model_d(sf: np.ndarray, p_bust: float, n: int = 10_000, seed: int = 1, n_jobs: int = 2) -> dict:
    """Total credit loss ($B) for each of n draws. Result is identical for any n_jobs (chunk seeds are fixed up front)."""
    n_chunks = 8
    sizes = [n // n_chunks + (1 if i < n % n_chunks else 0) for i in range(n_chunks)]
    seeds = np.random.SeedSequence(seed).spawn(n_chunks)
    parts = Parallel(n_jobs=n_jobs)(delayed(_d_chunk)(s, m, sf, p_bust) for s, m in zip(seeds, sizes))
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def run_model_f(sf: np.ndarray, p_bust: float, emulator, n: int = 10_000, seed: int = 2) -> dict:
    rng = np.random.default_rng(seed)
    shock = V.draw_shocks(sf, p_bust, rng, n)
    o = emulator.sample(shock, rng)
    return {"shock": shock,
            "spy_drawdown": o["sp500_dd"],
            "smh_drawdown": np.clip(o["ai_dd"] * SMH_BETA_TO_AI_INDEX, 0, 0.95),
            "sovereign_spend_usd_bn": o["sov_spend"],
            "credit_loss_usd_bn": o["credit_loss"]}


def run(sf, p_bust, n=10_000, seed=1, n_jobs=2):
    em, meta = surrogate_f.load()
    t = time.time()
    d = run_model_d(sf, p_bust, n, seed, n_jobs)
    f = run_model_f(sf, p_bust, em, n, seed + 1)
    return d, f, meta, round(time.time() - t, 2)
