"""Generate the training set for the Model F emulator by running the real agent-based model (ai_bust_abm.py).

    python scripts/train_surrogate_f.py [n_draws=360] [workers=2]     # about 0.9 s per draw per core

Shocks are stratified over the full 0-56% range (not drawn from the odds-weighted sampler) so the emulator sees the
tail. Parameter priors are the ones ``ai_bust_abm.monte_carlo`` uses. Writes quant/f_training.json.
Run once, or whenever ai_bust_abm.py changes; the nightly pipeline never calls the ABM.
"""
import hashlib, json, os, sys, time
from dataclasses import replace
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ai_bust_abm as F  # noqa: E402

PARAM_PRIORS = {"beta_gdp": (1.5, 3.5), "beta_equity": (0.1, 0.4), "ltv_covenant": (0.75, 0.90), "arb_capital": (20, 60),
                "rental_elasticity": (0.4, 0.9), "funding_slope": (3, 7), "capex_speed": (1, 3), "backstop_budget": (75, 250)}


def job(p):
    base, scen = F.simulate(p, return_base=True)
    s = F.excess(base, scen)
    return {"roi_shock": p.roi_shock, **{k: getattr(p, k) for k in PARAM_PRIORS},
            "sp500_dd": float(s["sp500_drawdown"]), "ai_dd": float(1 - s["ai_index_min"]),
            "credit_loss": float(s["excess_credit_losses"]), "sov_spend": float(s["excess_sovereign_spend"])}


def main(n=360, workers=2, seed=424242):
    rng = np.random.default_rng(seed)
    shocks = (np.arange(n) + rng.random(n)) / n * 0.56
    rng.shuffle(shocks)
    plist = [replace(F.Params(), roi_shock=float(s), seed=int(rng.integers(1e9)),
                     **{k: float(rng.uniform(*v)) for k, v in PARAM_PRIORS.items()}) for s in shocks]
    t = time.time()
    with Pool(workers) as pool:
        rows = pool.map(job, plist, chunksize=4)
    src = hashlib.sha256(open(os.path.join(ROOT, "ai_bust_abm.py"), "rb").read()).hexdigest()[:16]
    out = {"n": n, "seed": seed, "abm_sha256_16": src, "runtime_s": round(time.time() - t, 1), "param_priors": PARAM_PRIORS, "rows": rows}
    json.dump(out, open(os.path.join(ROOT, "quant", "f_training.json"), "w"))
    print(f"wrote {n} ABM draws in {out['runtime_s']} s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 360, int(sys.argv[2]) if len(sys.argv) > 2 else 2)
