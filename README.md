# When the Buildout Breaks

**How likely is an AI investment bust, and how bad would it be?** Models, simulations, a live-data dashboard and the working paper behind them.

**Live:** [aibust.ykhalil.com](https://aibust.ykhalil.com/) (dashboard) and [the paper](https://aibust.ykhalil.com/paper). Built by [Yassin Khalil](https://ykhalil.com/) ([LinkedIn](https://www.linkedin.com/in/yassin-khalil/)).

> **Not investment advice.** Everything here is model output for analysis, resting on stated judgment calls. It is not a forecast or a recommendation. The paper, the code and the documentation were written by Claude (Anthropic) at the direction of Yassin Khalil.

## What it answers

Two events are tracked separately:

- **Market crash**: chip stocks (SOX) fall 40% or more from a peak.
- **Economic bust**: end-customer AI spending falls 15% or more below the path the buildout was planned for.

Four independent estimates (a revenue simulation, history, market prices, warning indicators) are pooled into one set of odds. Two damage models (a 12-sector contagion network and a weekly agent-based model of firms, lenders and policy) then show who loses what if a bust happens.

### Published results (inputs as of 5 October 2026)

| Cumulative odds, median (10th–90th percentile) | End-2027 | End-2028 | End-2029 |
|---|---|---|---|
| Market crash | 37% (29–44%) | 52% (42–61%) | 58% (48–66%) |
| Economic bust | 17% (12–23%) | 30% (21–39%) | 40% (29–50%) |

Weighted by those odds: expected credit losses of \$23–57B depending on the model; a neocloud fails in 22–32% of futures; no bank fails in any simulated future. These come from the pooled odds (`ai_bust_probability.py`), the sector network (Model D) and the agent-based model (Model F). **Read the limitations before quoting any number**, in particular that the odds hinge on whether credit markets (which imply about 11%) are right.

## Quick start

Python 3.12, about 2 CPU cores.

```bash
git clone https://github.com/YassinKhalil/when-the-buildout-breaks.git && cd when-the-buildout-breaks
bash setup.sh                      # venv, dependencies, the 10 unit tests, an offline end-to-end run
export AI_BUST_UA="Your Name your@email"   # SEC requires a descriptive User-Agent
python ai_bust_live.py refresh --live      # pull live data and recompute (about 90 s)
bash start.sh                      # dashboard on 127.0.0.1:8000
python build_site.py               # build the paper page, served at /paper
```

The dashboard has **no login**. It binds to `127.0.0.1` only; view it over an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 user@server`). To publish it, put a reverse proxy in front that allows only GET and HEAD and blocks `/api/refresh`
(see `deploy/Caddyfile.example`).

## Nightly quantitative pipeline (10,000 draws)

`python scripts/run_pipeline.py` pulls SPY/SMH prices and SMH option vol (yfinance) and the high-yield spread and T-bill rate (FRED; set `FRED_API_KEY` or it uses the keyless CSV), re-pools the paper's odds on them, then runs **10,000 draws** each of Model D (exact, numpy-vectorised, parallel with joblib, checked against the scalar model in `test_quant.py`) and Model F (a regression emulator fitted to 360 real agent-based runs; `scripts/train_surrogate_f.py` regenerates the training set). It writes `public/data/latest_run.json` (EV = median, VaR95, CVaR95, histogram buckets, density curves) and appends a row to `public/data/historical_risk.csv`. The whole run takes a few seconds.

`.github/workflows/daily-sim.yml` runs it every weekday night and commits the two files. The front end (`public/index.html`, `public/ui/`) only reads them; the app serves it at `/`, the paper inside it behind "View Working Paper & Deep Dive", and the original dashboard at `/dashboard`. `deploy/ai-bust-sync.*` is an optional timer that pulls the commit on the server.

## Reproducing the results

| Command | What it does | Time on 2 vCPUs |
|---|---|---|
| `python ai_bust_probability.py --fast` | the odds only (writes `probability_results_fast.json`) | about 1.5 min |
| `python ai_bust_probability.py` | the full run: odds, sensitivities, expected damage (rewrites `probability_results.json`) | about 9 min |
| `python run_abm_final.py 24` | Model F ablation, cliff curve and knockout tests (rewrites `abm_final_*.json`) | about 23 min |
| `python ai_bust_probability.py --calibrate-mapping` | rebuilds the shock-to-outcome mapping (rewrites `abm_shock_to_realised.json`) | about 1 min |
| `python -m unittest test_ai_bust_live` | the unit tests | under 1 s |

Seeds are fixed. Parts I and III reproduce the published odds exactly; Model F shows small run-to-run differences even with fixed seeds (about \$0.2B on a \$22.6B expected loss in the re-run), so treat small Model F differences as noise.
Back up a result file before re-running the command that overwrites it. The 6 October 2026 reproduction is in `probability_results_rerun_20261006.json` and Section 18 of the paper.

## What is in the repository

| Path | Contents |
|---|---|
| `ai_bust_probability.py` | Part I (Model G, history, market, indicators, pooling) and Part III (expected damage) |
| `ai_bust_models.py` | Models A–E: revenue gap, depreciation, neocloud solvency, contagion network (Model D), macro transmission |
| `ai_bust_abm.py` | Model F, the weekly agent-based model with nine switchable mechanisms |
| `run_abm_final.py` | Model F ablation, cliff and knockout runs |
| `ai_bust_live.py`, `dashboard.html`, `manual_inputs.json` | Live-data pipeline, API and dashboard |
| `build_site.py`, `working_paper.md` | Builds the paper as a web page |
| `*.json` | Published results; `fixtures/` the recorded snapshot of the paper's inputs |
| `docs/` | **Full specification** (equations, algorithms, parameters), the paper, data sources |
| `deploy/` | Example Caddy and systemd files |

**Documentation:** [overview and simulation register](docs/01-overview.md) · [Models A–E](docs/02-models-A-to-E.md) · [Part I and Model G](docs/03-part-I-odds-model-G.md) · [Model F](docs/04-model-F-agent-based.md) ·
[live pipeline](docs/05-live-pipeline.md) · [data and assumptions](docs/06-data-and-assumptions.md) · [the paper](docs/paper.md)

## Known limitations

- The live fetchers have run against the real servers once. Stooq now answers with a bot-check page, so Yahoo Finance is the working price feed.
- Credit spreads, option-implied volatility, lab revenue and neocloud backlog have no free feed; they come from `manual_inputs.json` and are flagged as manual. Model G stays at its paper calibration.
- Model F ablations are noisy and only loosely paired across seeds, and its no-shock baseline is not quiet. Its "S&P 500" is a synthetic index, and its lender network is stylised.
- The dashboard's contagion panel averages over all shock draws; it is not conditional on a bust.
- The paper's conclusions depend on judgment calls it states and varies (when the boom began, how a shortfall maps onto Model F, how strongly the Fed, sovereign buyers and the power grid respond).

## Credit and citation

If you use the code, the results or the text, **please credit the work.**

- **Required by the license** (Apache-2.0, section 4): if you redistribute this work or a derivative, keep the [`LICENSE`](LICENSE) and the attribution in [`NOTICE`](NOTICE).
- **Asked as a courtesy**: say that you used it and cite the paper:

> Khalil, Y. (2026). *When the Buildout Breaks: How Likely Is an AI Bust, and How Bad Would It Be?* Working paper, Edition 2. Written by Claude (Anthropic).

```bibtex
@techreport{khalil2026buildout,
  author      = {Khalil, Yassin},
  title       = {When the Buildout Breaks: How Likely Is an AI Bust, and How Bad Would It Be?},
  year        = {2026},
  type        = {Working paper, Edition 2},
  note        = {Written by Claude (Anthropic). Code and results: see repository}
}
```

GitHub also reads [`CITATION.cff`](CITATION.cff) ("Cite this repository").

## License

- **Code** (`*.py`, `*.sh`, `dashboard.html`, `deploy/`, tests): [Apache License 2.0](LICENSE). It permits use, modification and redistribution, including commercially, provided you keep the license and the `NOTICE`, mark changes, and accept that it comes with **no warranty**.
- **Paper, documentation and published results** (`docs/`, `working_paper.md`, `*.json`, `fixtures/`): [Creative Commons Attribution 4.0 International](LICENSE-DOCS). Reuse is allowed with credit, a link to the license, and an indication of changes.
- **Third-party data** you download with the pipeline (U.S. Treasury, SEC EDGAR, FRED, Yahoo Finance) remains under its provider's terms. The repository does not redistribute raw feeds.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Please do not commit the `live_history.db` database, credentials or server addresses.
