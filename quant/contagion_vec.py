"""
Vectorised Model D (contagion network) and Model E (macro transmission).

Same equations as ``ai_bust_models.run_contagion`` / ``model_e`` (legal friction off), but every quantity carries a
leading *draw* axis, so 10,000 draws run as a handful of numpy array operations instead of 10,000 Python loops.
Network constants are imported from ``ai_bust_models`` so the two implementations cannot drift apart;
``tests/test_quant.py`` checks this module against the scalar reference draw by draw.

Output is continuous: total credit loss in $B per draw (no crash / no-crash flag).
"""
from __future__ import annotations

import numpy as np

import ai_bust_models as D

SECTORS, IDX, N = D.SECTORS, D.IDX, D.N
F0, CAPEX_MASK, KONTRACT = D.F0, D.CAPEX_MASK, D.KONTRACT
CLAIMS = D.CLAIMS
HORIZON = D.HORIZON

_EXOG = np.array([D.EXOG_REV.get(s, 0) for s in SECTORS], dtype=float)
_VARC = np.array([D.VAR_COST.get(s, 0.3) for s in SECTORS], dtype=float)
_BASE_REV = F0.sum(axis=0) + _EXOG
_F0_IN = F0.sum(axis=0)                                  # AI-driven inflow per sector
_AI_SHARE = np.divide(_F0_IN, _BASE_REV, out=np.zeros(N), where=_BASE_REV > 0)
_CLAIM_A = np.array([IDX[a] for a, _, _ in CLAIMS])
_CLAIM_B = np.array([IDX[b] for _, b, _ in CLAIMS])
_CLAIM_V = np.array([v for _, _, v in CLAIMS], dtype=float)
_CLAIM_FIRE = np.array([b in ("Neoclouds", "DC developers") for _, b, _ in CLAIMS])
_BUF_BASE = np.array([D.BUFFER[s] for s in SECTORS], dtype=float)
_PC, _BK, _PN, _EN = IDX["Private credit"], IDX["Banks"], IDX["Pensions & insurers"], IDX["Enterprise demand"]
_CHIP = IDX["Chip designers"]
_HS, _NC, _LAB, _DC = IDX["Hyperscalers"], IDX["Neoclouds"], IDX["Frontier labs"], IDX["DC developers"]
_BURN = [(IDX[s], v) for s, v in D.BURN.items()]
_REFI = [(IDX[s], v) for s, v in D.REFI.items()]
_NONEXT = np.arange(N) != _EN
# capex-like outflows from sectors other than chip designers, for the capex-cut statistic
_CAPEX_STAT = CAPEX_MASK.copy()
_CAPEX_STAT[_CHIP, :] = False


def run_contagion_batch(demand_shock, accel, distress_cut, lgd, fire_sale, buffer_scale, lab_funding_freeze,
                        refi_sens, rounds: int = 12) -> dict:
    """Vectorised ``run_contagion`` (legal_on=False). All arguments are 1-D arrays of length B."""
    shock = np.asarray(demand_shock, dtype=float)
    B = shock.shape[0]
    col = lambda x: np.asarray(x, dtype=float)[:, None]          # (B,) -> (B,1)
    accel, distress_cut, lgd, fire_sale = col(accel), col(distress_cut), col(lgd), col(fire_sale)
    refi_sens = np.asarray(refi_sens, dtype=float)
    freeze = np.asarray(lab_funding_freeze, dtype=float)
    lgd1, fire1 = lgd[:, 0], fire_sale[:, 0]
    bscale = np.asarray(buffer_scale, dtype=float)
    buffer = _BUF_BASE[None, :] * bscale[:, None]                 # (B,N)

    loss = np.zeros((B, N))
    defaulted = np.zeros((B, N), dtype=bool)
    cut = np.zeros((B, N)); cut[:, _EN] = shock
    capex_cut = np.zeros((B, N))
    paid = np.zeros((B, len(CLAIMS)))                             # credit loss booked per claim

    F = np.broadcast_to(F0, (B, N, N))
    chip_collapse = np.zeros(B)
    rev_short = np.zeros((B, N))
    for _ in range(rounds):
        protect = KONTRACT[None, :, :] * (~defaulted)[:, :, None]
        F = np.where(CAPEX_MASK[None, :, :],
                     F0[None] * (1 - capex_cut[:, :, None]),
                     F0[None] * (1 - cut[:, :, None] * (1 - protect)))
        rev = F.sum(axis=1) + _EXOG
        rev_short = np.clip(_BASE_REV - rev, 0, None)
        profit_loss = rev_short * (1 - _VARC) * HORIZON
        rsf = np.divide(rev_short, _BASE_REV, out=np.zeros_like(rev_short), where=_BASE_REV > 0)

        funding = np.zeros((B, N))
        for i, burn in _BURN:
            funding[:, i] += burn * np.minimum(1.0, freeze + 1.5 * rsf[:, i])
        lender_stress = np.minimum(1.0, 0.7 * np.minimum(loss[:, _PC] / D.BUFFER["Private credit"], 1)
                                   + 0.3 * np.minimum(loss[:, _BK] / D.BUFFER["Banks"], 1))
        for i, due in _REFI:
            bstress = np.minimum(1.0, 2.0 * rsf[:, i] + np.minimum(profit_loss[:, i] / buffer[:, i], 1))
            funding[:, i] += due * np.minimum(1.0, refi_sens * (0.6 * bstress + 2.0 * lender_stress))

        chip_collapse = 1 - F[:, :, _CHIP].sum(axis=1) / F0[:, _CHIP].sum()
        for k in range(len(CLAIMS)):
            ib = _CLAIM_B[k]
            v = _CLAIM_V[k]
            l = lgd1 + np.where(_CLAIM_FIRE[k], fire1 * chip_collapse, 0.0)
            owed = v * np.minimum(l, 0.95)
            stress = np.minimum(1.0, loss[:, ib] / np.maximum(_BUF_BASE[ib] * bscale, 1e-9))
            target = np.where(defaulted[:, ib], owed, v * 0.10 * stress)
            paid[:, k] = np.where(target - paid[:, k] > 0, target, paid[:, k])

        lp_loss = paid[:, _CLAIM_A == _PC].sum(axis=1) * D.LP_STAKE_SHARE
        total_credit = np.zeros((B, N))
        for a in np.unique(_CLAIM_A):
            total_credit[:, a] = paid[:, _CLAIM_A == a].sum(axis=1)
        total_credit[:, _PN] += lp_loss

        loss = profit_loss + total_credit + funding
        loss[:, _EN] = 0
        depletion = np.clip(loss / buffer, 0, None)
        defaulted |= depletion >= 1.0

        ai_short = rev_short / np.maximum(_F0_IN, 1e-9)
        dep1 = np.minimum(depletion, 1)
        new_cut = np.minimum(0.9, 0.5 * rsf + distress_cut * 0.3 * dep1)
        new_capex = np.minimum(0.95, accel * ai_short * np.maximum(_AI_SHARE, 0.35) / 0.35 * 0.5 + distress_cut * dep1)
        cut = np.where(defaulted, np.maximum(cut, 0.6), new_cut)
        capex_cut = np.where(defaulted, 1.0, new_capex)
        cut[:, _EN] = shock                                       # enterprise demand is the exogenous shock
        capex_cut[:, _EN] = 0.0

    base_capex = F0[_CAPEX_STAT].sum()
    now_capex = F[:, _CAPEX_STAT].sum(axis=1)
    return {
        "credit_losses": paid.sum(axis=1),
        "capex_cut": 1 - now_capex / base_capex,
        "chip_revenue_fall": chip_collapse,
        "hs_depletion": depletion[:, _HS],
        "defaulted": defaulted,
        "bank_loss": loss[:, _BK],
        "pension_loss": loss[:, _PN],
        "total_loss": loss.sum(axis=1) - loss[:, _PN] + total_credit[:, _PN],
    }


def model_e_batch(capex_cut, ai_dd, credit_losses, spill) -> dict:
    inv = capex_cut * D.AI_CAPEX_US_SHARE * D.DOMESTIC_CONTENT * D.MULTIPLIER
    sp = D.AI_INDEX_WEIGHT * ai_dd + (1 - D.AI_INDEX_WEIGHT) * ai_dd * spill
    wealth = D.HH_EQUITY * sp * D.MPC_WEALTH / D.US_GDP
    credit = credit_losses * 2.0 * 0.05 / D.US_GDP
    gdp = inv + wealth + credit
    return {"gdp_hit_pct": gdp * 100, "sp500_drawdown": sp}


def draw_shocks(sf: np.ndarray, p_bust: float, rng: np.random.Generator, n: int) -> np.ndarray:
    """Vector form of ``ai_bust_probability.reweighted_sampler``: P(shortfall >= 15%) is pinned to ``p_bust``."""
    hi = sf[sf >= 0.15]
    lo = sf[sf < 0.15]
    pick_hi = rng.random(n) < p_bust
    return np.where(pick_hi, rng.choice(hi, n), rng.choice(lo, n))


def draw_parameters(shock: np.ndarray, rng: np.random.Generator) -> dict:
    """Same prior as ``ai_bust_models.monte_carlo`` (one value per draw)."""
    n = shock.shape[0]
    p = dict(
        accel=rng.triangular(1.0, 1.8, 3.0, n),
        distress_cut=rng.uniform(0.3, 0.9, n),
        lgd=rng.uniform(0.35, 0.75, n),
        fire_sale=rng.uniform(0.1, 0.5, n),
        buffer_scale=rng.uniform(0.8, 1.2, n),
        refi_sens=rng.uniform(0.5, 1.5, n),
    )
    p["lab_funding_freeze"] = np.clip(1.2 * shock + rng.uniform(-0.15, 0.25, n), 0.0, 0.85)
    p["valuation_reset"] = rng.uniform(0.0, 0.30, n)
    p["spill"] = rng.uniform(0.2, 0.5, n)
    return p


def simulate_chunk(shock: np.ndarray, params: dict) -> dict:
    """Model D then Model E for one chunk of draws."""
    d = run_contagion_batch(shock, params["accel"], params["distress_cut"], params["lgd"], params["fire_sale"],
                            params["buffer_scale"], params["lab_funding_freeze"], params["refi_sens"])
    earnings_hit = 0.5 * np.minimum(d["hs_depletion"] * 3, 1) + 0.5 * np.minimum(d["chip_revenue_fall"], 1)
    expect_hit = 0.7 * shock
    ai_dd = np.minimum(0.9, 1 - (1 - params["valuation_reset"]) * (1 - 0.8 * earnings_hit) * (1 - expect_hit))
    e = model_e_batch(d["capex_cut"], ai_dd, d["credit_losses"], params["spill"])
    return {
        "credit_loss_usd_bn": d["credit_losses"],
        "ai_equity_dd": ai_dd,
        "gdp_hit_pct": e["gdp_hit_pct"],
        "neocloud_default": d["defaulted"][:, _NC],
        "lab_default": d["defaulted"][:, _LAB],
        "bank_default": d["defaulted"][:, _BK],
        "bank_loss_usd_bn": d["bank_loss"],
        "pension_loss_usd_bn": d["pension_loss"],
    }
