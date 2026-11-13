"""Routes for the unified static front end (public/): overview page, /ui assets, /data files and the paper as an embeddable fragment.

ai_bust_live.py calls ``register(app, HERE)`` at start-up; everything here is read-only GET.
The paper fragment is derived from paper.html (built by build_site.py) on first request and cached by file mtime, so
build_site.py stays the single source of the paper.
"""
from __future__ import annotations

import os
import re

_CACHE: dict = {}
SITE = "https://aibust.ykhalil.com"

DATA_DICTIONARY = {
    "file": "latest_run.json", "updated": "nightly, weekdays ~22:40 UTC", "licence": "CC BY 4.0 (data), Apache-2.0 (code)",
    "units": {"credit_loss": "USD billions", "drawdown": "fraction of today's price (0.25 = 25% fall)", "sovereign_spend": "USD billions"},
    "metric_blocks": {
        "ev": "50th percentile of the 10,000 simulated outcomes, used as the base case",
        "mean": "arithmetic mean (weights the tail)", "p10/p90": "10th / 90th percentile",
        "var95": "Value at Risk: the 95th percentile; 1 in 20 futures is worse",
        "cvar95": "Conditional VaR: mean of the worst 5% of futures",
        "p_zero": "share of futures with essentially no loss (no bust)",
        "histogram": "edges (n+1), counts (n) and overflow count above the last edge",
        "curve": "smoothed density on a grid, x and y arrays"},
    "paths": {
        "odds.economic_bust.<horizon>": "pooled probability that end-customer AI spending falls 15%+ below plan (median, p10, p90, mean)",
        "odds.market_crash.<horizon>": "pooled probability that chip stocks (SOX) fall 40%+ from peak",
        "model_d.credit_loss": "Model D contagion network: total credit loss to lenders (metric block, USD bn)",
        "model_f.spy_drawdown / smh_drawdown": "Model F (emulated) fall in SPY / SMH (metric blocks)",
        "model_f.sovereign_spend": "Model F government rescue spend (metric block, USD bn)",
        "inputs": "live SPY/SMH prices, SMH volatility, high-yield spread, with per-field provenance"},
    "also": {"history": "/data/historical_risk.csv (one row per night)", "summary": "/llms-full.txt", "paper": "/paper.md"},
    "caveats": "Model output on stated assumptions; not a forecast or investment advice. Model F outputs come from an emulator of the agent-based model."}


def summary_md(run: dict) -> str:
    """Plain-language markdown of the latest run: every headline number, the method and the caveats. Used by /llms-full.txt, content negotiation and the no-JS fallback."""
    pc = lambda x, d=0: f"{100 * x:.{d}f}%"
    usd = lambda b: f"${b / 1000:.2f}T" if abs(b) >= 1000 else f"${b:.0f}B" if abs(b) >= 10 else f"${b:.1f}B"
    d, f, i, o = run["model_d"], run["model_f"], run["inputs"], run["odds"]
    cl, smh, spy, sov = d["credit_loss"], f["smh_drawdown"], f["spy_drawdown"], f["sovereign_spend"]
    e28, c28 = o["economic_bust"]["end-2028"], o["market_crash"]["end-2028"]
    L = [f"# AI Bust Odds: latest simulation ({run['as_of_date']})", "",
         "> How likely is an AI investment bust, and how bad would it be? Nightly Monte Carlo of two damage models "
         f"({run['n_draws']:,} draws each) on live market data. Model output on stated assumptions, not a forecast or investment advice.", "",
         "## Odds (pooled from four independent methods)", "",
         f"- Economic bust (end-customer AI spending 15%+ below plan) by end-2028: **{pc(e28['median'])}** (10th-90th percentile {pc(e28['p10'])}-{pc(e28['p90'])}).",
         f"- Market crash (chip index SOX down 40%+) by end-2028: **{pc(c28['median'])}** ({pc(c28['p10'])}-{pc(c28['p90'])}).", "",
         "## Damage if it happens (all 10,000 futures, unconditional on a bust)", "",
         f"- Credit losses to lenders (Model D): base case (median) {usd(cl['ev'])}, mean {usd(cl['mean'])}, VaR95 {usd(cl['var95'])}, CVaR95 {usd(cl['cvar95'])}.",
         f"- A neocloud fails in {pc(d['p_neocloud_default'])} of futures; a frontier lab in {pc(d['p_lab_default'])}; a bank in {pc(d['p_bank_default'], 1)}.",
         f"- SMH drawdown (Model F): base case {pc(smh['ev'])}, VaR95 {pc(smh['var95'])}, CVaR95 {pc(smh['cvar95'])}.",
         f"- SPY drawdown (Model F): base case {pc(spy['ev'])}, VaR95 {pc(spy['var95'])}, CVaR95 {pc(spy['cvar95'])}.",
         f"- Sovereign rescue spend (Model F): base case {usd(sov['ev'])}, VaR95 {usd(sov['var95'])}, CVaR95 {usd(sov['cvar95'])}; none needed in {pc(sov['p_zero'])} of futures.", ""]
    for sym, inp, dd in (("SPY", i.get("spy"), spy), ("SMH", i.get("smh"), smh)):
        if inp and inp.get("price"):
            P = inp["price"]
            L.append(f"- {sym} last close ${P:,.2f} ({inp['date']}): base case implies ${P * (1 - dd['ev']):,.0f}; tail (CVaR95) implies ${P * (1 - dd['cvar95']):,.0f}. Scenario levels, not price targets.")
    L += ["", "## How to read the numbers", "",
          "- The distribution is not a bell curve: most futures show little loss (no bust) and a second hump holds the busts, so the median is far below the mean.",
          "- Base case = median. VaR95 = 95th percentile. CVaR95 = average of the worst 5%.",
          "- Rating bands applied on the site to CVaR95: credit loss LOW <$10B, MODERATE <$50B, HIGH <$250B, else CRITICAL; SMH drawdown <20% / <35% / <55%; sovereign spend <$25B / <$100B / <$200B.",
          "- Model D is exact (vectorised network model). Model F outputs come from a regression emulator fitted to 360 runs of the agent-based model.", "",
          "## Machine-readable sources", "",
          f"- [latest_run.json]({SITE}/data/latest_run.json): every metric, histogram and density curve. Data dictionary: [{SITE}/data/schema.json]({SITE}/data/schema.json)",
          f"- [historical_risk.csv]({SITE}/data/historical_risk.csv): one row per night",
          f"- [Working paper, markdown]({SITE}/paper.md) and [HTML]({SITE}/paper)",
          "- [Source code](https://github.com/YassinKhalil/when-the-buildout-breaks)", "",
          "Author: Yassin Khalil (https://ykhalil.com/). Paper, code and documentation written by Claude (Anthropic) at the author's direction."]
    return "\n".join(L)


LLMS_TXT = f"""# AI Bust Odds

> A quantitative working paper and nightly risk run on how likely an AI investment bust is and how bad it would be: pooled odds, a contagion network (Model D), an agent-based model (Model F), 10,000 draws each, with expected value, VaR and CVaR. Model output on stated assumptions; not investment advice.

## Start here
- [Latest results in plain language]({SITE}/llms-full.txt): every headline number, how to read it, caveats
- [Latest results, JSON]({SITE}/data/latest_run.json): full metrics, histograms, density curves
- [Data dictionary]({SITE}/data/schema.json): units and meaning of every field

## Data and paper
- [Nightly history, CSV]({SITE}/data/historical_risk.csv)
- [Working paper, markdown]({SITE}/paper.md)
- [Working paper, HTML]({SITE}/paper)
- [Interactive overview]({SITE}/)

## Code
- [Repository](https://github.com/YassinKhalil/when-the-buildout-breaks): models, pipeline, tests
- [Rendered docs and source]({SITE}/open-source/)

## Optional
- [Original live dashboard]({SITE}/dashboard)
"""


def _load_run(here: str):
    import json
    p = os.path.join(here, "public", "data", "latest_run.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def jsonld(run: dict | None) -> str:
    import json
    ds = {"@context": "https://schema.org", "@type": "Dataset", "name": "AI bust risk simulation: nightly results",
          "description": "Expected value, VaR95 and CVaR95 of credit losses, SPY/SMH drawdowns and sovereign rescue spend from 10,000-draw Monte Carlo runs of two AI-bust damage models, updated each weekday.",
          "url": SITE + "/", "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
          "creator": {"@type": "Person", "name": "Yassin Khalil", "url": "https://ykhalil.com/"},
          "temporalCoverage": "2026-11-13/..", "dateModified": (run or {}).get("generated_at"),
          "variableMeasured": ["Credit loss (USD bn)", "SMH drawdown", "SPY drawdown", "Sovereign rescue spend (USD bn)", "Probability of economic bust", "Probability of market crash"],
          "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE + "/data/latest_run.json"},
                           {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": SITE + "/data/historical_risk.csv"}]}
    return '<script type="application/ld+json">' + json.dumps(ds) + "</script>"


def paper_fragment(paper_html: str) -> str:
    """paper.html -> a self-contained <style> + contents list + <article>, scoped for a shadow root (no header, sidebar, scripts or live box)."""
    css = re.search(r"<style>(.*?)</style>", paper_html, re.S).group(1)
    css = css.replace(":root", ":host")
    css = re.sub(r"html\{scroll-behavior:smooth;scroll-padding-top:64px\}", "", css)
    css = re.sub(r"(?m)^body\{", ".pb{", css)                       # the page body becomes the wrapper div
    css = re.sub(r"body\.tocopen[^}]*\}", "", css)
    css += """
.pb{background:transparent;font-size:17px}
article{max-width:none;padding-bottom:20px}
.titleblock{padding-top:8px}
details.toc-d{font:14px "Geist",system-ui,sans-serif;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:8px 0 14px}
details.toc-d summary{cursor:pointer;font-weight:600}
details.toc-d .toc-links{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:2px 18px;margin-top:10px}
details.toc-d a{display:flex;gap:7px;color:var(--mute);text-decoration:none;padding:4px 6px;border-radius:6px}
details.toc-d a:hover{color:var(--ink);background:var(--soft)}
details.toc-d a.grp{grid-column:1/-1;margin-top:8px;color:var(--ink);font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:11px}
details.toc-d a.l3{display:none}
details.toc-d .num{min-width:22px;color:var(--acc);font-weight:600}
details.toc-d .subs{display:none}
"""
    toc = re.search(r'<aside class="toc">(.*?)</aside>', paper_html, re.S).group(1)
    toc = re.sub(r'<a href="#top"><b>Abstract</b></a><a href="#live">Live update</a>', '<a class="grp" href="#top">Abstract</a>', toc)
    toc = re.sub(r'<div class="subs"[^>]*>.*?</div>', "", toc, flags=re.S)          # subsections stay out of the compact list
    art = re.search(r'<article id="top">.*?</article>', paper_html, re.S).group(0)
    art = re.sub(r'<div class="box" id="live">.*?</div></div>', "", art, count=1, flags=re.S)
    return f'<style>{css}</style><div class="pb"><details class="toc-d"><summary>Contents</summary><div class="toc-links">{toc}</div></details>{art}</div>'


def register(app, here: str) -> None:
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    pub = os.path.join(here, "public")

    class NoCache(StaticFiles):
        async def get_response(self, path, scope):
            r = await super().get_response(path, scope)
            r.headers["Cache-Control"] = "no-cache"          # nightly data must never be served stale; the files are small
            return r

    @app.get("/paper-fragment", response_class=HTMLResponse)
    def fragment():
        path = os.path.join(here, "paper.html")
        if not os.path.exists(path):
            raise HTTPException(404, "paper.html not built; run build_site.py")
        m = os.path.getmtime(path)
        if _CACHE.get("m") != m:
            _CACHE.update(m=m, html=paper_fragment(open(path, encoding="utf-8").read()))
        return HTMLResponse(_CACHE["html"], headers={"Cache-Control": "no-cache"})

    from fastapi import Request
    from fastapi.responses import PlainTextResponse, Response

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms():
        return PlainTextResponse(LLMS_TXT, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache"})

    @app.get("/llms-full.txt", response_class=PlainTextResponse)
    def llms_full():
        run = _load_run(here)
        if run is None:
            raise HTTPException(404, "no run yet")
        return PlainTextResponse(summary_md(run), media_type="text/markdown; charset=utf-8", headers={"Cache-Control": "no-cache"})

    @app.get("/data/schema.json")
    def schema():
        return Response(__import__("json").dumps(DATA_DICTIONARY, indent=1), media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/paper.md", response_class=PlainTextResponse)
    def paper_md():
        path = os.path.join(here, "working_paper.md")
        if not os.path.exists(path):
            raise HTTPException(404, "paper not available")
        return PlainTextResponse(open(path, encoding="utf-8").read(), media_type="text/markdown; charset=utf-8")

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {SITE}/sitemap.xml\n")

    @app.get("/sitemap.xml")
    def sitemap():
        urls = ["/", "/paper", "/llms.txt", "/llms-full.txt", "/paper.md", "/data/latest_run.json", "/data/schema.json", "/open-source/"]
        body = "".join(f"<url><loc>{SITE}{u}</loc></url>" for u in urls)
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>", media_type="application/xml")

    @app.get("/dashboard", response_class=HTMLResponse)
    def legacy_dashboard():
        with open(os.path.join(here, "dashboard.html"), encoding="utf-8") as f:       # the original live-feed dashboard, kept
            return f.read()

    if os.path.isdir(os.path.join(pub, "ui")):
        app.mount("/ui", NoCache(directory=os.path.join(pub, "ui")), name="ui")
    if os.path.isdir(os.path.join(pub, "data")):
        app.mount("/data", NoCache(directory=os.path.join(pub, "data")), name="data")


def index_html(here: str) -> str | None:
    """The overview page with, for readers that do not run JavaScript, the structured data and a server-rendered summary."""
    p = os.path.join(here, "public", "index.html")
    if not os.path.exists(p):
        return None
    page = open(p, encoding="utf-8").read()
    run = _load_run(here)
    page = page.replace("<!--JSONLD-->", jsonld(run))
    if run:
        import html, re
        md = summary_md(run)
        body = html.escape(md)
        body = re.sub(r"^# (.*)$", r"<h2>\1</h2>", body, flags=re.M)
        body = re.sub(r"^## (.*)$", r"<h3>\1</h3>", body, flags=re.M)
        body = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", body)
        body = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', body)
        body = re.sub(r"^(?:- |&gt; )(.*)$", r"<p>\1</p>", body, flags=re.M)
        page = page.replace("<!--SSR-->", '<noscript><section class="wrap card">' + body + "</section></noscript>")
    return page
