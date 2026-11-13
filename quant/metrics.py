"""Institutional risk metrics from a 1-D array of outcomes where larger = worse (loss $, drawdown fraction, spend $)."""
from __future__ import annotations

import numpy as np


def risk_metrics(x: np.ndarray, bins: int = 40, tail_q: float = 0.95, clip_q: float = 0.995) -> dict:
    """EV (50th percentile, as the base case), mean, VaR95, CVaR95 (mean of the worst 5%), and chart-ready buckets.

    The histogram runs from 0 (or the minimum) to the 99.5th percentile so one extreme draw cannot flatten the chart;
    draws above the top edge are counted in ``overflow``. ``curve`` is a smoothed density on the same axis for the area chart.
    """
    x = np.sort(np.asarray(x, dtype=float))
    n = x.size
    var = float(np.quantile(x, tail_q))
    tail = x[x >= var]
    cvar = float(tail.mean())
    lo = float(min(0.0, x[0]))
    hi = float(np.quantile(x, clip_q))
    if hi <= lo:
        hi = lo + 1e-9 + abs(lo) * 1e-6 + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(x[x <= hi], bins=edges)
    width = edges[1] - edges[0]
    # smoothed density curve: Gaussian-kernel smoothing of the histogram on a finer grid (robust to point masses at 0)
    grid = np.linspace(lo, hi, 161)
    h = max(width * 1.2, (hi - lo) / 200)
    fine, _ = np.histogram(x[x <= hi], bins=np.linspace(lo, hi, 641))
    centres = (np.linspace(lo, hi, 641)[:-1] + np.linspace(lo, hi, 641)[1:]) / 2
    dens = np.array([(fine * np.exp(-0.5 * ((g - centres) / h) ** 2)).sum() for g in grid])
    dens = dens / (dens.sum() * (grid[1] - grid[0]) + 1e-300)
    return {
        "n": int(n),
        "ev": float(np.quantile(x, 0.5)),          # 50th percentile: the base case
        "mean": float(x.mean()),
        "p10": float(np.quantile(x, 0.10)),
        "p90": float(np.quantile(x, 0.90)),
        "var95": var,
        "cvar95": cvar,
        "max": float(x[-1]),
        "p_zero": float(np.mean(x <= 1e-9)),
        "histogram": {"edges": [round(float(e), 6) for e in edges],
                      "counts": [int(c) for c in counts],
                      "overflow": int(np.sum(x > hi))},
        "curve": {"x": [round(float(g), 6) for g in grid], "y": [round(float(d), 8) for d in dens]},
    }
