"""Nightly pipeline: live data -> Part I odds -> 10,000-draw Models D and F -> institutional metrics -> static files.

    python scripts/run_pipeline.py [--draws 10000] [--seed N] [--offline] [--out public/data]

Writes   public/data/latest_run.json          full metrics, histograms and density curves for the front end
Appends  public/data/historical_risk.csv      one row per date (a same-day re-run replaces that day's row)

--offline skips every network call and uses the paper's 5 Oct 2026 inputs (flagged as such in the output).
Exits non-zero if SPY and SMH prices could not be fetched, so a bad night never commits stale numbers as if they were fresh.
"""
import argparse, csv, datetime as dt, json, os, sys, time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ai_bust_probability as P  # noqa: E402
from quant import data as qdata, engine, metrics  # noqa: E402

CSV_COLS = ["date", "p_bust_2028", "p_crash_2028", "d_credit_ev_bn", "d_credit_cvar95_bn", "f_spy_dd_ev", "f_spy_dd_cvar95",
            "f_smh_dd_ev", "f_smh_dd_cvar95", "f_sov_ev_bn", "f_sov_cvar95_bn", "spy_price", "smh_price", "hy_oas_bps"]


def part1(live: dict, seed: int, n: int):
    """Re-pool the paper's four odds methods with live market inputs; also return the shortfall sample Model D/F draw shocks from."""
    saved_live = {k: v for k, v in P.LIVE.items()}
    try:
        P.LIVE.update(live)
        res = P.run_live(n=n, seed=seed, n_d=10, with_f=False)
        saved = (P.N, P.RNG)
        P.N, P.RNG = n, np.random.default_rng(seed)
        try:
            fund = P.fundamentals(P.RNG)
            sf = P.max_shortfall(fund["sim"], P.HORIZONS["end-2028"])
        finally:
            P.N, P.RNG = saved
        return res, sf
    finally:
        P.LIVE.clear(); P.LIVE.update(saved_live)


def r(x, k=4):
    return None if x is None else round(float(x), k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "public", "data"))
    a = ap.parse_args()
    t0 = time.time()
    today = dt.date.today()
    seed = a.seed if a.seed is not None else int(today.strftime("%Y%m%d"))

    feeds = {"spy": None, "smh": None, "hy": None, "tbill": None, "sources": {}} if a.offline else qdata.collect()
    if not a.offline and not (feeds["spy"] and feeds["smh"]):
        print("FATAL: could not fetch SPY/SMH prices:", json.dumps(feeds["sources"], indent=1), file=sys.stderr)
        sys.exit(1)
    paper_live = {k: (tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in P.LIVE.items()}
    live, prov = qdata.to_live_overrides(feeds, paper_live)

    res, sf = part1(live, seed, a.draws)
    p_bust = res["economic_bust"]["end-2028"]["median"]
    d, f, f_meta, t_engine = engine.run(sf, p_bust, a.draws, seed)

    spy, smh = feeds["spy"] or {}, feeds["smh"] or {}
    dm = {
        "unit": "USD billions",
        "credit_loss": metrics.risk_metrics(d["credit_loss_usd_bn"]),
        "p_neocloud_default": r(d["neocloud_default"].mean()), "p_lab_default": r(d["lab_default"].mean()),
        "p_bank_default": r(d["bank_default"].mean()),
        "gdp_hit_pct": {k: r(v) for k, v in metrics.risk_metrics(d["gdp_hit_pct"], bins=10).items() if k in ("ev", "mean", "var95", "cvar95")},
    }
    fm = {
        "spy_drawdown": metrics.risk_metrics(f["spy_drawdown"]),
        "smh_drawdown": metrics.risk_metrics(f["smh_drawdown"]),
        "sovereign_spend": {"unit": "USD billions", **metrics.risk_metrics(f["sovereign_spend_usd_bn"])},
        "method": "emulator of the agent-based model, fitted to real ABM runs",
        "emulator": f_meta,
        "smh_beta_to_ai_index": engine.SMH_BETA_TO_AI_INDEX,
    }
    odds = {k: {h: {x: r(v) for x, v in res[k][h].items()} for h in res[k]} for k in ("economic_bust", "market_crash")}
    out = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": str(today), "mode": "offline-paper-inputs" if a.offline else "live", "seed": seed, "n_draws": a.draws,
        "runtime_s": {"engine": t_engine, "total": round(time.time() - t0, 1)},
        "inputs": {"spy": spy, "smh": smh,
                   "hy_oas_bps": r((feeds["hy"] or {}).get("value", np.nan) * 100, 0) if feeds["hy"] else None,
                   "hy_oas_paper_ref_bps": r(feeds["hy"]["ref_value"] * 100, 0) if feeds["hy"] and feeds["hy"].get("ref_value") else None,
                   "tbill_pct": (feeds["tbill"] or {}).get("value"),
                   "part1_live_inputs": {k: list(v) if isinstance(v, tuple) else v for k, v in live.items()},
                   "provenance": prov, "sources": feeds["sources"]},
        "odds": odds,
        "model_d": dm, "model_f": fm,
        "notes": ["Distributions are unconditional on a bust: most draws sit near zero, the tail carries the risk.",
                  "Model D draws credit losses from the exact network model (vectorised, checked against the scalar code); legal friction off.",
                  "Model F outputs come from a regression emulator of the agent-based model (see model_f.emulator for held-out skill).",
                  "SMH drawdown = Model F AI-index drawdown x smh_beta_to_ai_index; SPY drawdown = Model F synthetic broad index.",
                  "Not investment advice; model output resting on stated judgment calls."],
    }
    os.makedirs(a.out, exist_ok=True)
    tmp = os.path.join(a.out, "latest_run.json.tmp")
    json.dump(out, open(tmp, "w"), separators=(",", ":"))
    os.replace(tmp, os.path.join(a.out, "latest_run.json"))

    row = {"date": str(today), "p_bust_2028": r(p_bust), "p_crash_2028": r(res["market_crash"]["end-2028"]["median"]),
           "d_credit_ev_bn": r(dm["credit_loss"]["ev"], 2), "d_credit_cvar95_bn": r(dm["credit_loss"]["cvar95"], 2),
           "f_spy_dd_ev": r(fm["spy_drawdown"]["ev"]), "f_spy_dd_cvar95": r(fm["spy_drawdown"]["cvar95"]),
           "f_smh_dd_ev": r(fm["smh_drawdown"]["ev"]), "f_smh_dd_cvar95": r(fm["smh_drawdown"]["cvar95"]),
           "f_sov_ev_bn": r(fm["sovereign_spend"]["ev"], 2), "f_sov_cvar95_bn": r(fm["sovereign_spend"]["cvar95"], 2),
           "spy_price": spy.get("price"), "smh_price": smh.get("price"), "hy_oas_bps": out["inputs"]["hy_oas_bps"]}
    path = os.path.join(a.out, "historical_risk.csv")
    rows = []
    if os.path.exists(path):
        rows = [x for x in csv.DictReader(open(path)) if x["date"] != row["date"]]
    rows.append({k: ("" if v is None else v) for k, v in row.items()})
    rows.sort(key=lambda x: x["date"])
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS); w.writeheader(); w.writerows(rows)
    print(f"ok  {a.draws} draws  engine {t_engine}s  total {out['runtime_s']['total']}s  p_bust2028={p_bust:.3f}  "
          f"D credit EV ${dm['credit_loss']['ev']:.1f}B CVaR95 ${dm['credit_loss']['cvar95']:.0f}B  "
          f"SMH dd EV {fm['smh_drawdown']['ev']:.1%} CVaR95 {fm['smh_drawdown']['cvar95']:.1%}")


if __name__ == "__main__":
    main()
