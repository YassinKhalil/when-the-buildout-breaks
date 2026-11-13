"""
ai_bust_live.py
===============
Live-data pipeline and contagion dashboard for the AI-bust working paper.

    fetchers  ->  snapshot  ->  calibration  ->  models  ->  SQLite history  ->  FastAPI + dashboard

WHAT IS LIVE
  * Policy and long rates ................ U.S. Treasury daily par yield curve (fallback: FRED CSV)
  * Equity prices, drawdowns, volatility .. Yahoo chart API (fallback: Stooq daily CSV, now behind a bot check)
  * Debt maturity ladders, capex, revenue,
    interest, cash, lease liabilities ..... SEC EDGAR XBRL "companyfacts" (what the 10-K / 10-Q tables report)
  * Filing dates ......................... SEC EDGAR "submissions"
WHAT IS NOT LIVE (no free feed exists; supply it in manual_inputs.json and it is flagged as manual)
  * Credit spreads / CDS, option-implied volatility, lab revenue run-rates, neocloud contract backlog.
    Model G (end-customer AI revenue vs the capex plan) therefore stays at its paper calibration.

HOW IT FEEDS THE MODELS
  * Part I market-based odds  <- LIVE dict in ai_bust_probability.py (risk-free rate, volatility, SOX drawdown, spreads)
  * Model F                   <- Params overrides: policy rate rf0, hyperscaler capex plan, the neocloud debt MATURITY
                                 LADDER (loan maturities are drawn from the measured 10-K ladder)
  * Each refresh re-pools the four methods, re-runs a small Model F Monte Carlo and stores the result with its snapshot.

HONESTY NOTE (read this before relying on it)
  The build environment this was written in could not reach SEC, Treasury, FRED, Stooq or Yahoo from its shell, so the
  fetchers were NOT exercised against the live servers. Parsers are tested against recorded payloads whose layouts follow
  the providers' documented formats (one real Treasury header was confirmed by a web fetch); the end-to-end run was done
  on a recorded snapshot (fixtures/snapshot_recorded_2026-10-05.json), which is labelled mode="recorded" everywhere.
  The first live run on a networked machine should be watched; every source reports ok/error in /api/state.

USAGE
    pip install fastapi uvicorn numpy scipy
    python ai_bust_live.py refresh --recorded fixtures/snapshot_recorded_2026-10-05.json   # offline end-to-end run
    python ai_bust_live.py refresh --live                                                  # needs internet
    uvicorn ai_bust_live:app --port 8000        # dashboard at http://localhost:8000/ ; POST /api/refresh?mode=live
    AI_BUST_REFRESH_MIN=60 uvicorn ai_bust_live:app      # also refresh every 60 minutes
SEC requires a descriptive User-Agent: set AI_BUST_UA="Your Name your@email".
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import sqlite3
import statistics
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("AI_BUST_DB", os.path.join(HERE, "live_history.db"))
MANUAL_PATH = os.environ.get("AI_BUST_MANUAL", os.path.join(HERE, "manual_inputs.json"))
UA = os.environ.get("AI_BUST_UA", "ai-bust-research-paper contact@example.com")

# ------------------------------------------------------------------------------------------------
# 0. Configuration
# ------------------------------------------------------------------------------------------------
COMPANIES = {            # name: (CIK, role)
    "CoreWeave": ("0001769628", "neocloud"),
    "Oracle": ("0001341439", "hyperscaler"),
    "Microsoft": ("0000789019", "hyperscaler"),
    "Alphabet": ("0001652044", "hyperscaler"),
    "Amazon": ("0001018724", "hyperscaler"),
    "Meta": ("0001326801", "hyperscaler"),
    "Nvidia": ("0001045810", "vendor"),
}
SYMBOLS = {              # label: (stooq symbol, yahoo symbol)
    "SOX": ("^sox", "^SOX"), "NVDA": ("nvda.us", "NVDA"), "SPX": ("^spx", "^GSPC"),
    "MSFT": ("msft.us", "MSFT"), "ORCL": ("orcl.us", "ORCL"), "CRWV": ("crwv.us", "CRWV"),
}
PEAK_AFTER = "2026-05-01"        # the AI-equity peak the paper measures drawdowns from (June 2026)

TAGS = {
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "debt": ["LongTermDebt", "DebtInstrumentCarryingAmount", "LongTermDebtAndCapitalLeaseObligations"],
    "lease_liab": ["OperatingLeaseLiability", "FinanceLeaseLiability"],
}
LADDER_TAGS = ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
               "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
               "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",
               "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
               "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",
               "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"]


# ------------------------------------------------------------------------------------------------
# 1. HTTP (injectable, so tests never touch the network)
# ------------------------------------------------------------------------------------------------
def http_get(url: str, headers: dict | None = None, timeout: float = 20.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                          # network down, DNS, TLS ...
        raise ConnectionError(f"{type(e).__name__}: {e}") from e


# ------------------------------------------------------------------------------------------------
# 2. Parsers (pure functions)
# ------------------------------------------------------------------------------------------------
def _pct(x):
    try:
        return float(x) / 100.0
    except (TypeError, ValueError):
        return None


def parse_treasury_csv(text: str) -> dict:
    """Daily Treasury Par Yield Curve CSV: Date,"1 Mo","1.5 Month","2 Mo","3 Mo",...,"10 Yr",.. rows newest-first, % values."""
    rows = list(csv.DictReader(io.StringIO(text)))
    best = None
    for r in rows:
        try:
            d = dt.datetime.strptime(r["Date"].strip(), "%m/%d/%Y").date()
        except (KeyError, ValueError):
            continue
        if best is None or d > best[0]:
            best = (d, r)
    if best is None:
        raise ValueError("no parsable rows in Treasury CSV")
    d, r = best
    return {"date": d.isoformat(), "y3m": _pct(r.get("3 Mo")), "y2": _pct(r.get("2 Yr")), "y10": _pct(r.get("10 Yr")),
            "y30": _pct(r.get("30 Yr"))}


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """FRED fredgraph.csv: header 'observation_date,SERIES' (older: 'DATE,SERIES'), '.' = missing, values in %."""
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in (".", ""):
            try:
                out.append((r[0], float(r[1]) / 100.0))
            except ValueError:
                pass
    return out


def parse_stooq_csv(text: str) -> list[tuple[str, float]]:
    """Stooq daily CSV: Date,Open,High,Low,Close,Volume (oldest first)."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out.append((r["Date"], float(r["Close"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def parse_yahoo_chart(text: str) -> list[tuple[str, float]]:
    j = json.loads(text)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    return [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), c) for t, c in zip(ts, cl) if c is not None]


def price_metrics(series: list[tuple[str, float]], peak_after: str = PEAK_AFTER, vol_days: int = 30) -> dict:
    """Last close, peak since `peak_after`, drawdown from that peak, realised volatility (annualised, close-to-close)."""
    if len(series) < 3:
        raise ValueError("price series too short")
    series = sorted(series)
    last_d, last = series[-1]
    since = [c for d, c in series if d >= peak_after] or [c for _, c in series]
    peak = max(since)
    rets = [math.log(series[i][1] / series[i - 1][1]) for i in range(1, len(series)) if series[i - 1][1] > 0 and series[i][1] > 0]
    tail = rets[-vol_days:]
    vol = statistics.pstdev(tail) * math.sqrt(252) if len(tail) >= 5 else None
    return {"date": last_d, "last": last, "peak_since": peak, "drawdown": 1.0 - last / peak, "vol30": vol, "n": len(series)}


def _fact_entries(facts: dict, tag: str, unit: str = "USD") -> list[dict]:
    node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    return list(node["units"].get(unit, [])) if node and "units" in node else []


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def latest_instant(facts: dict, tags: list[str]) -> tuple[float | None, str | None, str | None]:
    """Latest balance-sheet value ($) among 10-K/10-Q facts across candidate tags -> (value, end date, tag)."""
    best = None
    for tag in tags:
        for e in _fact_entries(facts, tag):
            if e.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A") or "start" in e:
                continue
            key = (e["end"], e.get("filed", ""))
            if best is None or key > best[0]:
                best = (key, e["val"], tag)
    return (best[1], best[0][0], best[2]) if best else (None, None, None)


def _ttm_one(facts: dict, tag: str) -> tuple[float | None, str | None, str | None]:
    ents = [e for e in _fact_entries(facts, tag) if "start" in e and e.get("form") in ("10-K", "10-Q", "10-K/A", "10-Q/A")]
    annual = [e for e in ents if 350 <= _days(e["start"], e["end"]) <= 380]
    if not annual:
        return None, None, None
    fy = max(annual, key=lambda e: (e["end"], e.get("filed", "")))
    ytd = [e for e in ents if e["start"] > fy["end"] and 60 <= _days(e["start"], e["end"]) < 350]
    if ytd:
        cur = max(ytd, key=lambda e: (e["end"], _days(e["start"], e["end"]), e.get("filed", "")))
        span = _days(cur["start"], cur["end"])
        prior = [e for e in ents if abs(_days(e["start"], e["end"]) - span) <= 6
                 and abs(_days(e["end"], cur["end"]) - 365) <= 6]
        if prior:
            p = max(prior, key=lambda e: e.get("filed", ""))
            return fy["val"] + cur["val"] - p["val"], cur["end"], tag
    return fy["val"], fy["end"], tag


def ttm_duration(facts: dict, tags: list[str]) -> tuple[float | None, str | None, str | None]:
    """Trailing-twelve-month flow ($): last fiscal year + current YTD - prior-year YTD when both exist, else the last FY.
    Every candidate tag is tried and the one with the most recent period end wins, so a retired tag cannot shadow a current one."""
    best = None
    for tag in tags:
        res = _ttm_one(facts, tag)
        if res[0] is not None and (best is None or res[1] > best[1]):
            best = res
    return best or (None, None, None)


def parse_companyfacts(facts: dict) -> dict:
    """SEC XBRL companyfacts JSON -> metrics in $B (and a 6-bucket debt maturity ladder, $B)."""
    out = {"entity": facts.get("entityName"), "cik": facts.get("cik")}
    for key in ("capex", "revenue", "interest"):
        v, end, tag = ttm_duration(facts, TAGS[key])
        out[f"{key}_ttm"] = None if v is None else v / 1e9
        out[f"{key}_asof"], out[f"{key}_tag"] = end, tag
    for key in ("cash", "debt", "lease_liab"):
        v, end, tag = latest_instant(facts, TAGS[key])
        out[key] = None if v is None else v / 1e9
        out[f"{key}_asof"], out[f"{key}_tag"] = end, tag
    ladder, ends = [], []
    for tag in LADDER_TAGS:
        v, end, _ = latest_instant(facts, [tag])
        ladder.append(None if v is None else v / 1e9)
        ends.append(end)
    out["maturity_ladder"] = ladder if any(x is not None for x in ladder) else None
    out["maturity_asof"] = max([e for e in ends if e], default=None)
    return out


def parse_submissions(sub: dict) -> dict:
    rec = sub.get("filings", {}).get("recent", {})
    forms, dates = rec.get("form", []), rec.get("filingDate", [])
    out = {}
    for form in ("10-K", "10-Q", "8-K"):
        ds = [d for f, d in zip(forms, dates) if f == form]
        out[f"latest_{form.replace('-', '').lower()}"] = max(ds) if ds else None
    return out


# ------------------------------------------------------------------------------------------------
# 3. Snapshot
# ------------------------------------------------------------------------------------------------
def _src(ok, url=None, err=None, **kw):
    return {"ok": ok, "url": url, "error": err, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **kw}


def fetch_rates(get=http_get) -> tuple[dict, dict]:
    year = dt.date.today().year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
    try:
        status, text = get(url, timeout=60)          # treasury.gov takes 17-20 s to answer; the 20 s default timed out at random
        if status != 200:
            raise ConnectionError(f"HTTP {status}")
        return parse_treasury_csv(text), _src(True, url)
    except Exception as e:
        err = f"treasury: {e}"
    try:                                                            # FRED fallback
        out = {}
        for sid, key in (("DGS3MO", "y3m"), ("DGS10", "y10"), ("DGS2", "y2")):
            u = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={year - 1}-01-01"
            status, text = get(u)
            if status != 200:
                raise ConnectionError(f"HTTP {status}")
            s = parse_fred_csv(text)
            out[key], out["date"] = s[-1][1], s[-1][0]
        return out, _src(True, "FRED", err=f"fallback after {err}")
    except Exception as e2:
        return {}, _src(False, url, f"{err}; fred: {e2}")


def fetch_prices(label: str, get=http_get) -> tuple[dict, dict]:
    stq, yh = SYMBOLS[label]
    errs = []
    try:                                                            # Yahoo first: Stooq now sits behind a JavaScript bot check
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yh}?range=14mo&interval=1d"
        status, text = get(url)
        if status != 200:
            raise ConnectionError(f"HTTP {status}")
        return price_metrics(parse_yahoo_chart(text)), _src(True, url)
    except Exception as e:
        errs.append(f"yahoo: {e}")
    try:                                                            # Stooq stays as the fallback in case it opens up again
        start = (dt.date.today() - dt.timedelta(days=420)).strftime("%Y%m%d")
        url = f"https://stooq.com/q/d/l/?s={stq}&i=d&d1={start}&d2={dt.date.today().strftime('%Y%m%d')}"
        status, text = get(url)
        if status != 200 or "Date" not in text[:20]:
            raise ConnectionError(f"HTTP {status} / unexpected body")
        return price_metrics(parse_stooq_csv(text)), _src(True, url, err="; ".join(errs))
    except Exception as e:
        errs.append(f"stooq: {e}")
    return {}, _src(False, None, "; ".join(errs))


def fetch_company(name: str, get=http_get) -> tuple[dict, dict]:
    cik, role = COMPANIES[name]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        status, text = get(url, headers={"Accept-Encoding": "identity"})
        if status != 200:
            raise ConnectionError(f"HTTP {status}")
        m = parse_companyfacts(json.loads(text))
        m["role"] = role
        try:
            s2, t2 = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
            if s2 == 200:
                m.update(parse_submissions(json.loads(t2)))
        except Exception:
            pass
        return m, _src(True, url)
    except Exception as e:
        return {}, _src(False, url, str(e))


def load_manual(path: str = MANUAL_PATH) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def build_snapshot(get=http_get, manual: dict | None = None, previous: dict | None = None) -> dict:
    """Pull every source; a failed source falls back to the previous snapshot's value and is marked stale."""
    snap = {"mode": "live", "as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sources": {}, "rates": {}, "equities": {}, "companies": {}, "manual": manual if manual is not None else load_manual()}
    prev = previous or {}
    r, s = fetch_rates(get)
    snap["sources"]["rates"] = s
    snap["rates"] = r if s["ok"] else prev.get("rates", {})
    if not s["ok"] and prev.get("rates"):
        s["stale"] = True
    for label in SYMBOLS:
        m, s = fetch_prices(label, get)
        snap["sources"][f"px:{label}"] = s
        snap["equities"][label] = m if s["ok"] else prev.get("equities", {}).get(label, {})
        if not s["ok"] and prev.get("equities", {}).get(label):
            s["stale"] = True
    for name in COMPANIES:
        m, s = fetch_company(name, get)
        snap["sources"][f"sec:{name}"] = s
        snap["companies"][name] = m if s["ok"] else prev.get("companies", {}).get(name, {})
        if not s["ok"] and prev.get("companies", {}).get(name):
            s["stale"] = True
    return snap


# ------------------------------------------------------------------------------------------------
# 4. Calibration: snapshot -> model inputs
# ------------------------------------------------------------------------------------------------
PAPER_DEFAULTS = {"y3m": 0.044, "nvda_iv": 0.32, "nc_spread": 0.055, "oracle_cds": 0.0227, "sox_dd": 0.17, "sigma_realised": 0.39,
                  "hs_capex_plan0": 700.0}


def calibrate(snap: dict) -> dict:
    """Translate a snapshot into (a) Part I LIVE inputs and (b) Model F parameter overrides, with provenance for each."""
    man, rates, eq, co = snap.get("manual", {}), snap.get("rates", {}), snap.get("equities", {}), snap.get("companies", {})
    prov, diag = {}, {}

    def pick(name, live_val, manual_key=None, default=None):
        if manual_key and man.get(manual_key) is not None:
            prov[name] = "manual"
            return man[manual_key]
        if live_val is not None:
            prov[name] = "feed" if snap.get("mode") == "live" else "recorded"
            return live_val
        prov[name] = "paper default (no data)"
        return default

    y3m = pick("r_free", rates.get("y3m"), None, PAPER_DEFAULTS["y3m"])
    iv = pick("nvda_implied_vol", None, "nvda_iv", PAPER_DEFAULTS["nvda_iv"])
    real = pick("realised_vol", (eq.get("SOX") or eq.get("NVDA") or {}).get("vol30"), None, PAPER_DEFAULTS["sigma_realised"])
    dd = pick("sox_drawdown", (eq.get("SOX") or {}).get("drawdown"), None, PAPER_DEFAULTS["sox_dd"])
    spread = pick("nc_spread", None, "nc_spread", PAPER_DEFAULTS["nc_spread"])
    cds = pick("oracle_cds", None, "oracle_cds", PAPER_DEFAULTS["oracle_cds"])
    sig_lo = min(iv, real)
    sig_hi = max(iv, real) + 0.06
    part1 = {"r_free": y3m, "sigma": (round(sig_lo, 4), round(sig_hi, 4)),
             "sox_drawdown": (round(max(0.0, dd - 0.09), 4), round(min(0.6, dd + 0.01), 4)),
             "nc_spread": (round(spread - 0.01, 4), round(spread + 0.01, 4)), "oracle_cds": cds}

    # Model F overrides
    f_over = {"rf0": y3m}
    hs = [co.get(n, {}) for n, (_, role) in COMPANIES.items() if role == "hyperscaler"]
    capex = [c.get("capex_ttm") for c in hs if c.get("capex_ttm")]
    guide = man.get("hyperscaler_capex_plan_2027")
    if guide:
        f_over["hs_capex_plan0"] = float(guide)
        prov["hs_capex_plan0"] = "manual (guidance)"
    elif len(capex) >= 3:
        est = sum(capex) * (1.0 + man.get("capex_growth_to_2027", 0.25)) * (4.0 / len(capex)) ** 0
        f_over["hs_capex_plan0"] = float(min(max(est, 0.6 * 700), 1.5 * 700))
        prov["hs_capex_plan0"] = f"filings: TTM capex of {len(capex)} companies x (1+g), clipped to 0.6-1.5x the paper value"
    nc = co.get("CoreWeave", {})
    lad = nc.get("maturity_ladder")
    if lad:
        vals = [x or 0.0 for x in lad]
        profile = vals[:4] + [vals[4] + vals[5]]          # years 1-4, year 5 and beyond
        if sum(profile) > 0:
            f_over["nc_maturity_profile"] = tuple(round(x / sum(profile), 4) for x in profile)
            prov["nc_maturity_profile"] = f"CoreWeave 10-K/10-Q ladder as of {nc.get('maturity_asof')}"
    elif man.get("nc_maturity_profile"):
        f_over["nc_maturity_profile"] = tuple(man["nc_maturity_profile"])
        prov["nc_maturity_profile"] = "manual"
    # calibration diagnostics: model vs filings (not fed back automatically)
    if nc.get("debt") and nc.get("revenue_ttm"):
        diag["neocloud_debt_to_revenue"] = {"filings": nc["debt"] / nc["revenue_ttm"], "model_NC-1": 2.9}
    if nc.get("interest_ttm") and nc.get("debt"):
        diag["neocloud_avg_interest_rate"] = {"filings": nc["interest_ttm"] / nc["debt"], "model_ddtl": 0.09}
    diag["policy_rate_vs_model"] = {"live": y3m, "model_rf0": 0.044}
    return {"part1": part1, "model_f": f_over, "provenance": prov, "diagnostics": diag}


# ------------------------------------------------------------------------------------------------
# 5. Models
# ------------------------------------------------------------------------------------------------
def run_models(cal: dict, n=10_000, n_d=4_000, n_f=40) -> dict:
    import ai_bust_probability as P
    saved = {k: (tuple(v) if isinstance(v, tuple) else v) for k, v in P.LIVE.items()}
    try:
        P.LIVE.update({k: (tuple(v) if isinstance(v, list) else v) for k, v in cal["part1"].items()})
        f_over = {k: (tuple(v) if isinstance(v, list) else v) for k, v in cal["model_f"].items()}
        t0 = time.time()
        res = P.run_live(n=n, n_d=n_d, n_f=n_f, f_overrides=f_over)
        res["runtime_s"] = round(time.time() - t0, 1)
        return res
    finally:
        P.LIVE.clear()
        P.LIVE.update(saved)


# ------------------------------------------------------------------------------------------------
# 6. Storage
# ------------------------------------------------------------------------------------------------
def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, mode TEXT, snapshot TEXT, "
                "calibration TEXT, results TEXT, p_bust_2027 REAL, p_bust_2028 REAL, p_bust_2029 REAL, p_crash_2028 REAL, "
                "nc_fail REAL, exp_loss REAL)")
    return con


def store(snap: dict, cal: dict, res: dict) -> int:
    eb, mc = res["economic_bust"], res["market_crash"]
    f = res.get("expected_damage", {}).get("model_f", {})
    con = db()
    cur = con.execute("INSERT INTO runs (ts, mode, snapshot, calibration, results, p_bust_2027, p_bust_2028, p_bust_2029, "
                      "p_crash_2028, nc_fail, exp_loss) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (snap["as_of"], snap["mode"], json.dumps(snap), json.dumps(cal), json.dumps(res, default=float),
                       eb["end-2027"]["median"], eb["end-2028"]["median"], eb["end-2029"]["median"], mc["end-2028"]["median"],
                       f.get("p_neocloud_default"), f.get("expected_credit_losses")))
    con.commit()
    return cur.lastrowid


def latest_run() -> dict | None:
    row = db().execute("SELECT id, ts, mode, snapshot, calibration, results FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {"id": row[0], "ts": row[1], "mode": row[2], "snapshot": json.loads(row[3]), "calibration": json.loads(row[4]),
            "results": json.loads(row[5])}


def history(limit=200) -> list[dict]:
    rows = db().execute("SELECT id, ts, mode, p_bust_2027, p_bust_2028, p_bust_2029, p_crash_2028, nc_fail, exp_loss "
                        "FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    keys = ("id", "ts", "mode", "p_bust_2027", "p_bust_2028", "p_bust_2029", "p_crash_2028", "nc_fail", "exp_loss")
    return [dict(zip(keys, r)) for r in reversed(rows)]


# ------------------------------------------------------------------------------------------------
# 7. Refresh orchestration
# ------------------------------------------------------------------------------------------------
STATUS = {"running": False, "last_error": None, "last_finished": None, "last_mode": None}
_LOCK = threading.Lock()


def refresh(mode="live", recorded_path: str | None = None, get=http_get, **model_kw) -> dict:
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("a refresh is already running")
    STATUS.update(running=True, last_error=None, last_mode=mode)
    try:
        if mode == "recorded":
            with open(recorded_path or os.path.join(HERE, "fixtures", "snapshot_recorded_2026-10-05.json")) as f:
                snap = json.load(f)
            snap["mode"] = "recorded"
        else:
            prev = latest_run()
            snap = build_snapshot(get=get, previous=prev["snapshot"] if prev else None)
            if not any(s["ok"] for s in snap["sources"].values()):
                raise ConnectionError("no data source reachable: " + "; ".join(f"{k}: {v['error']}" for k, v in list(snap['sources'].items())[:3]))
        cal = calibrate(snap)
        res = run_models(cal, **model_kw)
        rid = store(snap, cal, res)
        STATUS["last_finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        return {"id": rid, "mode": snap["mode"]}
    except Exception as e:
        STATUS["last_error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        STATUS["running"] = False
        _LOCK.release()


# ------------------------------------------------------------------------------------------------
# 8. API + dashboard
# ------------------------------------------------------------------------------------------------
try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app):
        mins = float(os.environ.get("AI_BUST_REFRESH_MIN", "0") or 0)
        if mins > 0:
            def loop():
                while True:
                    try:
                        refresh("live")
                    except Exception:
                        pass
                    time.sleep(mins * 60)
            threading.Thread(target=loop, daemon=True).start()
        yield

    app = FastAPI(title="AI-bust contagion dashboard", lifespan=_lifespan)

    @app.get("/api/state")
    def api_state():
        r = latest_run()
        if r is None:
            return {"empty": True, "status": STATUS}
        snap = r["snapshot"]
        return {"id": r["id"], "ts": r["ts"], "mode": r["mode"], "status": STATUS, "sources": snap.get("sources", {}),
                "rates": snap.get("rates"), "equities": snap.get("equities"), "companies": snap.get("companies"),
                "manual": snap.get("manual"), "calibration": r["calibration"], "results": r["results"], "history": history()}

    @app.get("/api/history")
    def api_history():
        return history()

    @app.post("/api/refresh")
    def api_refresh(bg: BackgroundTasks, mode: str = "live"):
        if mode not in ("live", "recorded"):
            raise HTTPException(400, "mode must be live or recorded")
        if STATUS["running"]:
            raise HTTPException(409, "refresh already running")
        bg.add_task(_bg_refresh, mode)
        return {"started": True, "mode": mode}

    def _bg_refresh(mode):
        try:
            refresh(mode)
        except Exception:
            pass

    @app.get("/", response_class=HTMLResponse)
    def index():
        import unified_site                                  # unified overview + deep dive; falls back to the original dashboard
        page = unified_site.index_html(HERE)
        if page is not None:
            return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
        with open(os.path.join(HERE, "dashboard.html")) as f:
            return f.read()

    @app.get("/paper", response_class=HTMLResponse)
    def paper():
        path = os.path.join(HERE, "paper.html")          # built by build_site.py
        if not os.path.exists(path):
            raise HTTPException(404, "paper.html not built; run build_site.py")
        with open(path, encoding="utf-8") as f:
            return f.read()
    import unified_site
    unified_site.register(app, HERE)                                # /ui, /data, /paper-fragment, /dashboard
except ImportError:                                                 # fastapi not installed: CLI still works
    app = None


# ------------------------------------------------------------------------------------------------
# 9. CLI
# ------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Live-data pipeline for the AI-bust paper.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--recorded", metavar="SNAPSHOT_JSON")
    r.add_argument("--n", type=int, default=10_000)
    r.add_argument("--n-f", type=int, default=40)
    a = ap.parse_args()
    out = refresh("live" if a.live else "recorded", recorded_path=a.recorded, n=a.n, n_f=a.n_f)
    print(json.dumps(out), "->", DB_PATH)
