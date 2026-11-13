"""Live market inputs: SPY/SMH prices and SMH option-implied volatility (yfinance), high-yield spread (FRED).

Every fetch returns (value, provenance). A failed source never raises: the caller falls back to the paper's October-2026
inputs and the run is flagged in ``inputs.provenance`` so nobody mistakes a fallback for live data.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import os
import urllib.parse
import urllib.request

import numpy as np

PEAK_AFTER = "2026-05-01"        # same AI-equity peak window the paper measures drawdowns from (ai_bust_live.PEAK_AFTER)
PAPER_DATE = "2026-10-05"        # date of the paper's published inputs
HY_SERIES, TBILL_SERIES = "BAMLH0A0HYM2", "DTB3"


def _fred(series: str, timeout: float = 20.0) -> list[tuple[str, float]]:
    key = os.environ.get("FRED_API_KEY")
    if key:
        q = urllib.parse.urlencode({"series_id": series, "api_key": key, "file_type": "json", "observation_start": "2026-01-01"})
        import json
        raw = json.load(urllib.request.urlopen(f"https://api.stlouisfed.org/fred/series/observations?{q}", timeout=timeout))
        return [(o["date"], float(o["value"])) for o in raw["observations"] if o["value"] not in (".", "")]
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2026-01-01"       # keyless fallback
    text = urllib.request.urlopen(url, timeout=timeout).read().decode()   # a custom User-Agent makes FRED hang; the default works
    rows = list(csv.reader(io.StringIO(text)))[1:]
    return [(d, float(v)) for d, v in rows if v not in (".", "")]


def fetch_fred(series: str) -> tuple[dict | None, dict]:
    try:
        for attempt in range(3):                                   # FRED's csv endpoint is intermittently slow
            try:
                obs = _fred(series)
                break
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    raise
        ref = [v for d, v in obs if d <= PAPER_DATE]
        out = {"date": obs[-1][0], "value": obs[-1][1], "ref_value": ref[-1] if ref else None}
        return out, {"ok": True, "source": "FRED api" if os.environ.get("FRED_API_KEY") else "FRED csv", "series": series}
    except Exception as e:  # noqa: BLE001
        return None, {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "series": series}


def atm_implied_vol(tk, spot: float, min_days: int = 20) -> float | None:
    """30-day-ish at-the-money implied vol: median over live two-sided quotes within 5% of spot, calls and puts.
    Returns None (not a guess) when quotes are stale or implausible, e.g. when the market is closed and IVs read ~0."""
    today = dt.date.today()
    exps = [e for e in tk.options if (dt.date.fromisoformat(e) - today).days >= min_days]
    if not exps:
        return None
    ch = tk.option_chain(exps[0])
    vals = []
    for df in (ch.calls, ch.puts):
        near = df[(df["strike"] / spot - 1).abs() <= 0.05]
        near = near[(near["bid"] > 0) & (near["ask"] > 0) & (near["impliedVolatility"] > 0)]
        vals += list(near["impliedVolatility"])
    iv = float(np.median(vals)) if len(vals) >= 4 else None
    return iv if iv is not None and 0.08 <= iv <= 2.0 else None


def fetch_etf(symbol: str, with_iv: bool = True) -> tuple[dict | None, dict]:
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        h = tk.history(period="14mo", interval="1d", auto_adjust=False)["Close"].dropna()
        if len(h) < 60:
            raise ValueError("too little price history")
        spot = float(h.iloc[-1])
        since = h[h.index >= PEAK_AFTER]
        peak = float(since.max())
        rets = np.log(h).diff().dropna()
        out = {"symbol": symbol, "price": round(spot, 2), "date": str(h.index[-1].date()),
               "peak_since_may": round(peak, 2), "drawdown_from_peak": round(1 - spot / peak, 4),
               "rv30": round(float(rets.iloc[-30:].std() * math.sqrt(252)), 4)}
        iv, note = None, None
        if with_iv:
            try:
                iv = atm_implied_vol(tk, spot)
            except Exception as e:  # noqa: BLE001
                note = f"options: {type(e).__name__}: {e}"[:120]
        out["iv30"] = round(iv, 4) if iv else None
        return out, {"ok": True, "source": "yfinance", **({"note": note} if note else {})}
    except Exception as e:  # noqa: BLE001
        return None, {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "symbol": symbol}


def collect() -> dict:
    spy, s1 = fetch_etf("SPY", with_iv=False)
    smh, s2 = fetch_etf("SMH", with_iv=True)
    hy, s3 = fetch_fred(HY_SERIES)
    tb, s4 = fetch_fred(TBILL_SERIES)
    return {"spy": spy, "smh": smh, "hy": hy, "tbill": tb,
            "sources": {"spy": s1, "smh": s2, "hy_oas": s3, "tbill": s4}}


def to_live_overrides(d: dict, paper: dict) -> tuple[dict, dict]:
    """Map raw feeds to the ``LIVE`` dict that drives Part I's market-based odds (same mapping rules as ai_bust_live.calibrate).
    Returns (overrides, provenance). ``paper`` holds the paper's own LIVE defaults."""
    prov: dict[str, str] = {}
    live = dict(paper)
    smh = d.get("smh")
    if smh:
        rv = smh["rv30"]
        iv = smh.get("iv30")
        prov["sigma"] = "feed (SMH implied + realised)" if iv else "feed (SMH realised only; no option IV)"
        lo = min(iv, rv) if iv else rv
        hi = (max(iv, rv) if iv else rv) + 0.06
        live["sigma"] = (round(lo, 4), round(hi, 4))
        dd = smh["drawdown_from_peak"]
        live["sox_drawdown"] = (round(max(0.0, dd - 0.09), 4), round(min(0.6, dd + 0.01), 4))
        prov["sox_drawdown"] = "feed (SMH drawdown from peak since 1 May 2026, proxy for SOX)"
    else:
        prov["sigma"] = prov["sox_drawdown"] = "paper default (feed failed)"
    hy = d.get("hy")
    if hy and hy.get("ref_value") is not None:
        shift = (hy["value"] - hy["ref_value"]) / 100.0          # percentage points -> decimal
        lo, hi = paper["nc_spread"]
        live["nc_spread"] = (round(max(0.005, lo + shift), 4), round(max(0.015, hi + shift), 4))
        prov["nc_spread"] = f"paper range shifted by the change in ICE BofA HY OAS since {PAPER_DATE} ({shift * 1e4:+.0f} bp)"
    else:
        prov["nc_spread"] = "paper default (feed failed)"
    tb = d.get("tbill")
    if tb:
        live["r_free"] = round(tb["value"] / 100.0, 4)
        prov["r_free"] = "feed (FRED DTB3)"
    else:
        prov["r_free"] = "paper default (feed failed)"
    prov["oracle_cds"] = "paper default (no free feed)"
    return live, prov
