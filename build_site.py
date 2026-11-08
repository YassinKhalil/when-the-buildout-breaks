"""Builds paper.html (the paper as a single web page) from working_paper.md and the result files.

    python build_site.py            # writes paper.html next to this file

Nothing here changes the models or the paper source. Figures and tables are generated from the result JSON files, so the
page cannot drift from the data. Edits to stale statements in the paper text are listed in EDITS and in Appendix F.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sqlite3

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
J = lambda p: json.load(open(os.path.join(HERE, p)))
PR = J("probability_results.json")                      # the paper's published results (as of 2026-10-05)
ABL, CLIFF, KO = (J(f"abm_final_{k}.json") for k in ("ablation", "cliff", "knockout"))
MAP = J("abm_shock_to_realised.json")
BK = os.path.join(HERE, "backup_20261006")
EDITION_DATE = "6 October 2026"
pc = lambda x, d=0: "–" if x is None else f"{100 * x:.{d}f}%"
esc = html.escape


def pcr(x):
    """Percent as the paper prints it: round to three decimals, then half up (0.295 -> 30%)."""
    return "–" if x is None else f"{math.floor(round(x, 3) * 100 + 0.5):.0f}%"

# ---------------------------------------------------------------------------------------------------------------------
# Edits to stale statements (exact substring -> replacement). The build fails loudly if a source string is not found.
# ---------------------------------------------------------------------------------------------------------------------
EDITS = [
    ("A second program keeps these odds current. It is built but its live feeds were never run.",
     "A second program keeps these odds current. **[Updated 6 Oct 2026]** Its live feeds have now been run once against the real servers (Appendix B)."),
    ("- **Not exercised live.** The build environment could not reach Treasury, SEC or the price sources. The fetchers were tested only on recorded and synthetic payloads (10 automated tests pass), and the end-to-end run used a recorded snapshot dated 5 October 2026. The dashboard labels such runs “recorded snapshot”. Watch the first live run.",
     "- **First live run done (6 Oct 2026).** The original build environment could not reach the data sources, so the paper's own run used a recorded snapshot dated 5 October 2026. The first live run on a networked server reached Treasury, Yahoo and SEC; Stooq answered with a bot-check page and was covered by the Yahoo fallback. It exposed one parser bug (retired SEC tags shadowing current ones), now fixed. Details: Appendix B. The ten automated tests still use synthetic payloads."),
    ("- **Placeholders.** CoreWeave's debt-maturity ladder is a placeholder until a live filing parse succeeds.",
     "- **Placeholders.** The ladder in the recorded snapshot was a placeholder. **[Updated 6 Oct 2026]** The first live run replaced it with CoreWeave's ladder from its 10-Q as of 30 June 2026 (Appendix B)."),
    ("- **The live pipeline was never run against live feeds,** and the CoreWeave maturity ladder is a placeholder (section 16.1).",
     "- **The live pipeline has been run against live feeds once** (6 Oct 2026). Credit spreads, implied volatility, lab revenue and backlog remain manual inputs, and the Stooq feed is blocked (section 16.1, Appendix B)."),
    ("The full run, with the sensitivity tests, takes about 5½ minutes on two cores;",
     "The full run, with the sensitivity tests, takes about 5½ minutes on two cores (**measured 6 Oct 2026: 9 min 14 s** on a 2-vCPU server);"),
]

# ---------------------------------------------------------------------------------------------------------------------
# Figures (inline SVG, theme-aware via CSS variables)
# ---------------------------------------------------------------------------------------------------------------------
FIGS = []          # (id, caption, source)


def fig_wrap(inner, caption, source):
    FIGS.append(len(FIGS) + 1)
    n = len(FIGS)
    return (f'<figure class="fig" id="fig-{n}">{inner}<figcaption><b>Figure {n}.</b> {caption} '
            f'<span class="src">Source: {source}</span></figcaption></figure>')


def axis_grid(x0, x1, y0, y1, yticks, fmt, ymax):
    out = []
    for t in yticks:
        y = y1 - (y1 - y0) * t / ymax
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/><text x="{x0 - 6}" y="{y + 3:.1f}" text-anchor="end">{fmt(t)}</text>')
    return "".join(out)


def fig_odds():
    W, H, L, R, T, B = 640, 280, 46, 10, 22, 44
    pw = W - L - R
    groups = [("Economic bust", PR["economic_bust"], "var(--c1)"), ("Market crash", PR["market_crash"], "var(--c2)")]
    hz = ["end-2027", "end-2028", "end-2029"]
    s = [axis_grid(L, W - R, T, H - B, [0, .2, .4, .6, .8], lambda v: f"{int(v * 100)}%", 0.8)]
    gw = pw / 3
    for gi, h in enumerate(hz):
        for si, (name, d, col) in enumerate(groups):
            c = d[h]["combined"]
            x = L + gi * gw + gw * (0.2 + 0.32 * si)
            bw = gw * 0.26
            y = lambda v: H - B - (H - B - T) * v / 0.8
            s.append(f'<rect x="{x:.1f}" y="{y(c["median"]):.1f}" width="{bw:.1f}" height="{H - B - y(c["median"]):.1f}" fill="{col}" rx="2"/>')
            cx = x + bw / 2
            s.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(c["p10"]):.1f}" y2="{y(c["p90"]):.1f}" class="whisk"/>')
            s.append(f'<text x="{cx:.1f}" y="{y(c["p90"]) - 5:.1f}" text-anchor="middle" class="lab">{pcr(c["median"])}</text>')
        s.append(f'<text x="{L + gi * gw + gw / 2:.1f}" y="{H - B + 16}" text-anchor="middle">{h.replace("end-", "End-")}</text>')
    s.append(f'<rect x="{L}" y="{H - 14}" width="10" height="10" fill="var(--c1)"/><text x="{L + 14}" y="{H - 5}">Economic bust</text>'
             f'<rect x="{L + 110}" y="{H - 14}" width="10" height="10" fill="var(--c2)"/><text x="{L + 124}" y="{H - 5}">Market crash</text>'
             f'<text x="{W - R}" y="{H - 5}" text-anchor="end">bar = median, line = 10th–90th percentile</text>')
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Combined odds by horizon">{"".join(s)}</svg>',
                    "Combined cumulative odds of an economic bust and of a market crash.",
                    'S2 pooling of S1 · <a href="#sec-18-2">register</a> · probability_results.json')


def line_chart(series, xs, W, H, L, R, T, B, ymax, yfmt, xfmt, xticks, band=None):
    sx = lambda v: L + (W - L - R) * (v - xs[0]) / (xs[-1] - xs[0])
    sy = lambda v: H - B - (H - B - T) * v / ymax
    s = [axis_grid(L, W - R, T, H - B, [i * ymax / 4 for i in range(5)], yfmt, ymax)]
    for t in xticks:
        s.append(f'<text x="{sx(t):.1f}" y="{H - B + 16}" text-anchor="middle">{xfmt(t)}</text>')
    if band:
        for lo, hi, cls in band:
            pts = [f"{sx(x):.1f},{sy(v):.1f}" for x, v in zip(xs, hi)] + [f"{sx(x):.1f},{sy(v):.1f}" for x, v in reversed(list(zip(xs, lo)))]
            s.append(f'<polygon points="{" ".join(pts)}" class="{cls}"/>')
    for ys, col, dash, _ in series:
        d = "M" + "L".join(f"{sx(x):.1f},{sy(v):.1f}" for x, v in zip(xs, ys))
        s.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.4" {"stroke-dasharray=%r" % dash if dash else ""}/>')
    return "".join(s), sx, sy


def fig_fan():
    fan = PR["model_g"]["fan"]
    xs = [f["t"] for f in fan]
    W, H = 640, 270
    body, sx, sy = line_chart([([f["p50"] for f in fan], "var(--c1)", None, "median")], xs, W, H, 46, 24, 18, 44, 1.4,
                              lambda v: f"{v:.1f}", lambda t: f"{t:.0f}", [2027, 2028, 2029, 2030],
                              band=[([f["p10"] for f in fan], [f["p90"] for f in fan], "band1"), ([f["p25"] for f in fan], [f["p75"] for f in fan], "band2")])
    y85, y10 = sy(0.85), sy(1.0)
    body += (f'<line x1="46" x2="{W - 24}" y1="{y10:.1f}" y2="{y10:.1f}" class="ref"/><text x="{W - 26}" y="{y10 - 4:.1f}" text-anchor="end">on plan = 1.0</text>'
             f'<line x1="46" x2="{W - 24}" y1="{y85:.1f}" y2="{y85:.1f}" class="ref red"/><text x="{W - 26}" y="{y85 + 12:.1f}" text-anchor="end">bust line = 0.85</text>'
             f'<text x="50" y="{H - 6}">shaded: 25th–75th (dark) and 10th–90th (light) percentile of 40,000 paths</text>')
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Model G fan chart">{body}</svg>',
                    "Model G: end-customer AI revenue as a share of the plan path (1.0 = revenue keeps pace with the capital stock).",
                    'S1 · probability_results.json → model_g.fan')


def fig_cliff():
    cs = CLIFF["curves"]
    xs = [r["shock"] for r in next(iter(cs.values()))]
    W, H = 640, 270
    cols = {"v1 (all upgrades off)": "var(--c2)", "all on": "var(--c1)", "all on, no cfo agents": "var(--c3)"}
    ser = [([r["p_nc_fail"] for r in rows], cols.get(k, "var(--mute)"), "5 3" if "no cfo" in k else None, k) for k, rows in cs.items()]
    body, sx, sy = line_chart(ser, xs, W, H, 46, 24, 18, 56, 1.0, lambda v: f"{int(v * 100)}%", lambda t: f"{t * 100:.0f}%", [0, .1, .2, .3, .4, .55])
    lx = 50
    for _, col, dash, name in ser:
        body += f'<line x1="{lx}" x2="{lx + 18}" y1="{H - 10}" y2="{H - 10}" stroke="{col}" stroke-width="2.4" {"stroke-dasharray=%r" % dash if dash else ""}/><text x="{lx + 22}" y="{H - 6}">{esc(name)}</text>'
        lx += 24 + 6.2 * len(name)
    body += f'<text x="{(46 + W - 10) / 2}" y="{H - 28}" text-anchor="middle">demand shock</text>'
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Cliff curve">{body}</svg>',
                    f"Share of simulated futures in which at least one neocloud fails, by size of the demand shock ({CLIFF['n_seeds']} seeds per point, net of each seed's no-shock twin).",
                    'S8 · run_abm_final.py → abm_final_cliff.json')


def fig_exceed():
    d = PR["expected_damage"]["model_d"]["exceedance"]
    f = PR["expected_damage"]["model_f"]["exceedance"]
    W, H, L, R, T, B = 640, 250, 46, 10, 18, 52
    xmax = 350
    sx = lambda v: L + (W - L - R) * v / xmax
    sy = lambda v: H - B - (H - B - T) * v
    s = [axis_grid(L, W - R, T, H - B, [0, .25, .5, .75, 1.0], lambda v: f"{int(v * 100)}%", 1.0)]
    for t in (0, 50, 100, 150, 200, 250, 300, 350):
        s.append(f'<text x="{sx(t):.1f}" y="{H - B + 16}" text-anchor="middle">${t}B</text>')
    for rows, col, name, dash in ((d, "var(--c1)", "Model D (sector network)", None), (f, "var(--c2)", "Model F (firm-level)", None)):
        s.append(f'<path d="M{"L".join(f"{sx(r["loss"]):.1f},{sy(r["p"]):.1f}" for r in rows)}" fill="none" stroke="{col}" stroke-width="2.4"/>')
        for r in rows:
            s.append(f'<circle cx="{sx(r["loss"]):.1f}" cy="{sy(r["p"]):.1f}" r="2.6" fill="{col}"/>')
    s.append(f'<text x="{(L + W - R) / 2}" y="{H - 28}" text-anchor="middle">credit losses above this amount ($B)</text>'
             f'<line x1="{L + 4}" x2="{L + 22}" y1="{H - 10}" y2="{H - 10}" stroke="var(--c1)" stroke-width="2.4"/><text x="{L + 26}" y="{H - 6}">Model D (10,000 draws)</text>'
             f'<line x1="{L + 190}" x2="{L + 208}" y1="{H - 10}" y2="{H - 10}" stroke="var(--c2)" stroke-width="2.4"/><text x="{L + 212}" y="{H - 6}">Model F (400 draws)</text>')
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Loss exceedance curves">{"".join(s)}</svg>',
                    "Chance that expected credit losses exceed a given amount, weighted by the combined bust odds. Averages over all shock draws, not conditional on a bust.",
                    'S5 and S6 · probability_results.json → expected_damage')


def fig_by_shock():
    rows = PR["expected_damage"]["model_f_by_shock"]
    W, H, L, R, T, B = 640, 250, 46, 10, 18, 52
    s = [axis_grid(L, W - R, T, H - B, [0, .25, .5, .75, 1.0], lambda v: f"{int(v * 100)}%", 1.0)]
    gw = (W - L - R) / len(rows)
    for i, r in enumerate(rows):
        for j, (k, col) in enumerate((("p_neocloud_default", "var(--c1)"), ("p_fund_failure", "var(--c2)"))):
            x = L + i * gw + gw * (0.16 + 0.34 * j)
            bw = gw * 0.30
            h = (H - B - T) * r[k]
            s.append(f'<rect x="{x:.1f}" y="{H - B - h:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{col}" rx="2"/><text x="{x + bw / 2:.1f}" y="{H - B - h - 4:.1f}" text-anchor="middle" class="lab">{pc(r[k])}</text>')
        s.append(f'<text x="{L + i * gw + gw / 2:.1f}" y="{H - B + 16}" text-anchor="middle">shock {esc(r["shock"])}</text><text x="{L + i * gw + gw / 2:.1f}" y="{H - B + 28}" text-anchor="middle">n={r["n"]}</text>')
    s.append(f'<rect x="{L}" y="{H - 14}" width="10" height="10" fill="var(--c1)"/><text x="{L + 14}" y="{H - 5}">a neocloud fails</text>'
             f'<rect x="{L + 120}" y="{H - 14}" width="10" height="10" fill="var(--c2)"/><text x="{L + 134}" y="{H - 5}">a private-credit fund fails (any of ten)</text>')
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Model F by shock size">{"".join(s)}</svg>',
                    "Model F outcomes by size of the demand shock, across the 400 Part III draws.",
                    'S6 · probability_results.json → expected_damage.model_f_by_shock')


def fig_tornado():
    t = PR["tornado_g"]
    base = t["base"]
    keys = [k for k in t if k not in ("base", "stress")]
    keys.sort(key=lambda k: -abs(t[k]["p_at_high"] - t[k]["p_at_low"]))
    W, rh, L, R, T = 640, 22, 130, 14, 24
    H = T + rh * len(keys) + 34
    sx = lambda v: L + (W - L - R) * v
    s = [f'<line x1="{sx(base):.1f}" x2="{sx(base):.1f}" y1="{T - 6}" y2="{H - 28}" class="ref"/><text x="{sx(base):.1f}" y="{T - 10}" text-anchor="middle">base {pc(base, 1)}</text>']
    for i, k in enumerate(keys):
        y = T + i * rh
        a, b = t[k]["p_at_low"], t[k]["p_at_high"]
        s.append(f'<text x="{L - 6}" y="{y + 12}" text-anchor="end">{esc(k)} ({t[k]["low_value"]}–{t[k]["high_value"]})</text>'
                 f'<rect x="{sx(min(a, b)):.1f}" y="{y + 3}" width="{abs(sx(b) - sx(a)):.1f}" height="14" fill="var(--c1)" opacity=".85" rx="2"/>'
                 f'<text x="{sx(max(a, b)) + 4:.1f}" y="{y + 14}">{pc(min(a, b))}–{pc(max(a, b))}</text>')
    s.append(f'<text x="{L}" y="{H - 8}">P(economic bust by end-2028) with one Model G input at its low and high end</text>')
    return fig_wrap(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Tornado chart">{"".join(s)}</svg>',
                    "One-at-a-time sensitivity of the Model G bust probability (20,000 paths per setting).",
                    'S3 · probability_results.json → tornado_g')


# ---------------------------------------------------------------------------------------------------------------------
# Simulation register (counts come from the result files and the code constants)
# ---------------------------------------------------------------------------------------------------------------------
def runtimes():
    out = {}
    p = os.path.join(HERE, "heavy.log")
    if os.path.exists(p):
        for m in re.finditer(r"END rc=(\d+) (\d+)s :: \S+ (.+)", open(p).read()):
            out[m.group(3).strip()] = int(m.group(2))
    for m in re.finditer(r"(ablation|cliff|knockout) done (\d+)", open(p).read() if os.path.exists(p) else ""):
        out[m.group(1)] = int(m.group(2))
    return out


def fmt_s(s):
    return "–" if s is None else s if isinstance(s, str) else (f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s")


def register():
    rt = runtimes()
    cases = sorted({r["case"] for r in ABL["rows"]})
    n_abl = len(ABL["rows"])
    n_cliff = len(CLIFF["shocks"]) * CLIFF["n_seeds"] * len(CLIFF["curves"])
    ko_nodes = len(next(iter(KO.values()))["nodes"]) + 1
    n_ko = sum(v["n_seeds"] * ko_nodes for v in KO.values())
    n_map = len(MAP["shocks"]) * MAP["n_seeds"]
    t_prob = rt.get("ai_bust_probability.py")
    t_abl = rt.get("ablation")
    cl_all = rt.get("cliff")
    ko_all = rt.get("knockout")
    t_cliff = None if cl_all is None or t_abl is None else cl_all - t_abl
    t_ko = None if ko_all is None or cl_all is None else ko_all - cl_all
    t_map = rt.get("ai_bust_probability.py --calibrate-mapping")
    rows = [
        ("S1", "Model G Monte Carlo", "Monte Carlo over uncertain inputs: revenue paths vs the plan path", "40,000 paths", "20261005", "Part I, fundamentals estimate", "probability_results.json", "ai_bust_probability.py", "2 · 17", t_prob and f"{fmt_s(t_prob)} for S1–S6 together"),
        ("S2", "Pooling of the four methods", "Joint draws with random log-odds weights", "40,000 joint draws", "20261005", "Combined odds, leave-one-out", "probability_results.json", "ai_bust_probability.py", "6", None),
        ("S3", "Model G sensitivity", "One-at-a-time tornado plus 4 stress cases", "20,000 paths × 27 settings", "7", "Which inputs move the bust odds", "probability_results.json → tornado_g", "ai_bust_probability.py", "2.1 · App. C", None),
        ("S4", "Model G upgrade ladder", "Cumulative ladder and leave-one-out of the v2 upgrades", "40,000 paths × 11 specifications", "7", "What each Model G upgrade changes", "probability_results.json → g_upgrade_ablation", "ai_bust_probability.py", "2.1", None),
        ("S5", "Model D Monte Carlo", "Sector contagion network, 12 sectors, with and without legal friction", "10,000 draws × 2", "11 (sampler), 20260930 (model)", "Expected credit losses, defaults, exceedance", "probability_results.json → model_d, model_d_legal", "ai_bust_models.py", "11 · 13 · 15", None),
        ("S6", "Model F Monte Carlo (Part III)", "Weekly agent-based model with shortfalls drawn from Model G, each netted against a no-shock twin", "400 draws × 3 (v2, v1, alternative mapping)", "5", "Expected damage, by-shock table", "probability_results.json → model_f, model_f_v1, model_f_by_shock", "ai_bust_abm.py", "14.4 · 14.6 · 15", None),
        ("S7", "Model F ablation", f"Each of nine mechanisms added or removed, across {len(cases)} cases at 3 shock sizes", f"{n_abl:,} scenario runs ({len(cases)} cases × 3 shocks × {ABL['n_seeds']} seeds)", "1000–1023", "Which mechanisms move losses (noisy)", "abm_final_ablation.json", "run_abm_final.py", "14.5 · 14.6 · App. C", t_abl),
        ("S8", "Model F cliff curve", f"Chance of a neocloud failure along {len(CLIFF['shocks'])} shock sizes, {len(CLIFF['curves'])} configurations", f"{n_cliff:,} scenario runs ({len(CLIFF['shocks'])} shocks × {CLIFF['n_seeds']} seeds × {len(CLIFF['curves'])} cases)", "2000–2031", "Where the cliff is", "abm_final_cliff.json", "run_abm_final.py", "14.6 · App. C", t_cliff),
        ("S9", "Model F knockout", f"Wipe out one lender's capital at t = 1 year in a 15% shock; {ko_nodes - 1} nodes + control; two network designs", f"{n_ko:,} scenario runs ({ko_nodes} cases × {next(iter(KO.values()))['n_seeds']} seeds × 2 modes)", "3000–3023", "Is there a single point of failure?", "abm_final_knockout.json", "run_abm_final.py", "14.7 · App. C", t_ko),
        ("S10", "Shock-to-outcome mapping", "Calibrates Part I's shortfall to Model F demand shocks", f"{n_map} scenario runs ({len(MAP['shocks'])} shocks × {MAP['n_seeds']} seeds)", "1–12", "Mapping used by the credit-implied estimate", "abm_shock_to_realised.json", "ai_bust_probability.py --calibrate-mapping", "1 · 4", t_map),
        ("S11", "Live recalibration (each refresh)", "Re-pools the four methods and reruns a small Model D and F on live inputs", "10,000 paths · 4,000 D draws · 40 F draws", "20261006", "Dashboard odds and contagion panel", "live_history.db (SQLite)", "ai_bust_live.py", "16.1 · App. B", None),
    ]
    hdr = ("ID", "Simulation", "How many", "Seeds", "Output", "Used in", "Runtime, 6 Oct")
    body = "".join(
        f'<tr id="{r[0].lower()}"><td><b>{r[0]}</b></td><td><b>{esc(r[1])}</b><div class="kind">{esc(r[2])}. {esc(r[5])}.</div></td>'
        f'<td>{esc(r[3])}</td><td>{esc(r[4])}</td><td><code>{esc(r[6])}</code><div class="kind">{esc(r[7])}</div></td><td>{esc(r[8])}</td><td>{fmt_s(r[9])}</td></tr>' for r in rows)
    tot = n_abl + n_cliff + n_ko + n_map + 3 * 400
    table = f'<div class="scroll"><table class="reg"><thead><tr>{"".join(f"<th>{h}</th>" for h in hdr)}</tr></thead><tbody>{body}</tbody></table></div>'
    return table, tot, {"abl": n_abl, "cliff": n_cliff, "ko": n_ko, "map": n_map, "cases": len(cases)}


# ---------------------------------------------------------------------------------------------------------------------
# Results tables from the result files and a reproduction check against the files shipped with the paper
# ---------------------------------------------------------------------------------------------------------------------
def tbl(head, rows, cls=""):
    h = "".join(f"<th>{h}</th>" for h in head)
    b = "".join("<tr>" + "".join(f"<td{' class=n' if i else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def ablation_html():
    T = ABL["table"]
    names = list(T)
    rows = []
    for n in names:
        r = [esc(n)]
        for s in ("10%", "20%", "30%"):
            c = T[n].get(s)
            r.append("–" if not c else f'{c["credit_losses"]:.0f} ± {c["credit_losses_se"]:.0f} · {pc(c["p_nc_fail"])}')
        rows.append(r)
    return tbl(["Case", "10% shock", "20% shock", "30% shock"], rows, "compact")


def cliff_html():
    cs = CLIFF["curves"]
    keys = list(cs)
    xs = [r["shock"] for r in cs[keys[0]]]
    rows = []
    for i, x in enumerate(xs):
        rows.append([pc(x, 1)] + [f'{pc(cs[k][i]["p_nc_fail"])} · ${cs[k][i]["mean_credit_losses"]:.0f}B' for k in keys])
    return tbl(["Shock"] + [esc(k) for k in keys], rows, "compact")


def knockout_html():
    out = []
    for mode, d in KO.items():
        rows = [[esc(n), f'${v["ko_amount"]:.0f}B', f'${v["second_round_losses"]:.1f}B ± {v["second_round_se"]:.1f}', f'{v["extra_neoclouds_failed"]:.2f}', f'{v["extra_funds_failed"]:.2f}', f'{v["amplification"]:.2f}×']
                for n, v in d["nodes"].items()]
        out.append(f'<h4>Network design: {esc(mode)} ({d["n_seeds"]} seeds per node, shock {pc(d["shock"])})</h4>' +
                   tbl(["Node knocked out", "Capital wiped", "Second-round losses", "Extra neoclouds failed", "Extra funds failed", "Amplification"], rows, "compact"))
    return "".join(out)


def mapping_html():
    rows = [[pc(b["shock"], 1), pc(b["realised_bottom"], 1), f'{pc(b["lo"], 1)}–{pc(b["hi"], 1)}', pc(b["p_nc_fail"]), f'{b["ai_index_min_median"]:.2f}'] for b in MAP["by_shock"]]
    x = MAP["ai_crash_shock_F"]
    note = f'<p class="sub">AI-linked stocks fall 40% at a shock of {pc(x["median"], 1)} (inter-quartile {pc(x["q25"], 1)}–{pc(x["q75"], 1)}) across {MAP["n_seeds"]} seeds.</p>' if x.get("median") else ""
    return tbl(["Demand shock", "Realised bottom of demand (median)", "Range across seeds", "Share of seeds with a neocloud failure", "AI index minimum (median)"], rows, "compact") + note


def ladder_html():
    rows = [[esc(r["step"]), pc(r["end-2027"], 1), pc(r["end-2028"], 1), pc(r["end-2029"], 1), pc(r["market_crash_end-2028"], 1)] for r in PR["g_upgrade_ablation"]["ladder"]]
    return tbl(["Model G version", "Bust end-2027", "Bust end-2028", "Bust end-2029", "Crash end-2028"], rows, "compact")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def repro_html():
    parts = []
    fast_p = os.path.join(HERE, "probability_results_fast.json")
    rr_p = os.path.join(HERE, "probability_results_rerun_20261006.json")
    rows = []
    for label, p in (("--fast re-run (odds only)", fast_p), ("Full re-run", rr_p)):
        if not os.path.exists(p):
            continue
        n = json.load(open(p))
        mx = 0.0
        for d in ("economic_bust", "market_crash"):
            for h in PR[d]:
                mx = max(mx, abs(n[d][h]["combined"]["median"] - PR[d][h]["combined"]["median"]))
        row = [label, f"{mx:.2e}"]
        if "model_f" in n.get("expected_damage", {}):
            a, b = PR["expected_damage"]["model_f"], n["expected_damage"]["model_f"]
            row += [f'{a["expected_credit_losses"]:.2f} → {b["expected_credit_losses"]:.2f}', f'{pc(a["p_credit_gt_100"], 2)} → {pc(b["p_credit_gt_100"], 2)}', f'{pc(a["p_neocloud_default"], 2)} → {pc(b["p_neocloud_default"], 2)}']
        else:
            row += ["not run", "not run", "not run"]
        rows.append(row)
    if rows:
        parts.append("<h4>Part I and Part III</h4>" + tbl(["Re-run", "Largest change in any combined median", "Model F expected credit losses ($B)", "Model F: chance losses > $100B", "Model F: chance a neocloud fails"], rows, "compact"))
    rows = []
    for f, fn in (("abm_final_cliff.json", None), ("abm_final_ablation.json", None), ("abm_final_knockout.json", None), ("abm_shock_to_realised.json", None)):
        p0 = os.path.join(BK, f)
        if not os.path.exists(p0):
            continue
        o, n = json.load(open(p0)), J(f)
        same = o == n
        diff = ""
        if f == "abm_final_cliff.json":
            d = max(abs(a["p_nc_fail"] - b["p_nc_fail"]) for k in o["curves"] for a, b in zip(o["curves"][k], n["curves"][k]))
            diff = f"largest change in a neocloud-failure share: {100 * d:.1f} points"
        elif f == "abm_shock_to_realised.json":
            d = max(abs(a["p_nc_fail"] - b["p_nc_fail"]) for a, b in zip(o["by_shock"], n["by_shock"]))
            diff = f"largest change in a neocloud-failure share: {100 * d:.1f} points"
        elif f == "abm_final_ablation.json":
            d = max(abs(o["table"][c][s]["credit_losses"] - n["table"][c][s]["credit_losses"]) for c in o["table"] if c in n["table"] for s in o["table"][c] if s in n["table"][c])
            diff = f"largest change in mean credit losses: ${d:.1f}B"
        else:
            d = max(abs(o[m]["nodes"][k]["second_round_losses"] - n[m]["nodes"][k]["second_round_losses"]) for m in o for k in o[m]["nodes"] if k in n[m]["nodes"])
            diff = f"largest change in second-round losses: ${d:.1f}B"
        rows.append([f"<code>{f}</code>", "identical" if same else "re-generated", diff])
    if rows:
        parts.append("<h4>Model F sweeps (shipped file vs 6 Oct 2026 re-run)</h4>" + tbl(["File", "Result", "Difference"], rows, "compact"))
    return "".join(parts) or "<p class='sub'>No re-run files found.</p>"


def live_db():
    p = os.path.join(HERE, "live_history.db")
    if not os.path.exists(p):
        return None
    con = sqlite3.connect(p)
    r = con.execute("SELECT id, ts, mode, snapshot, calibration FROM runs WHERE mode='live' ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    return {"id": r[0], "ts": r[1], "snap": json.loads(r[3]), "cal": json.loads(r[4])}


def provenance_html():
    L = live_db()
    if not L:
        return "<p class='sub'>No live run stored yet.</p>"
    snap, cal = L["snap"], L["cal"]
    src = []
    for k, v in snap["sources"].items():
        st = "stale" if v.get("stale") else ("ok" if v["ok"] else "failed")
        src.append([esc(k), st, esc(str(v.get("error") or ""))[:120]])
    comp = []
    for n, c in snap["companies"].items():
        f = lambda x: "–" if x is None else f"{x:,.1f}"
        comp.append([esc(n), esc(c.get("role", "")), f(c.get("capex_ttm")), f(c.get("revenue_ttm")), f(c.get("debt")), esc(c.get("capex_asof") or "–")])
    prov = [[esc(k), esc(v)] for k, v in cal["provenance"].items()]
    lad = (snap["companies"].get("CoreWeave") or {}).get("maturity_ladder")
    lad_t = tbl(["Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Later", "Sum"], [[*(f"{x:.1f}" if x is not None else "–" for x in lad), f"{sum(x or 0 for x in lad):.1f}"]]) if lad else ""
    return (f'<p class="sub">Live run #{L["id"]}, {esc(L["ts"])}. Values in $B, trailing twelve months.</p>'
            + "<h4>Source status</h4>" + tbl(["Source", "Status", "Error text"], src, "compact")
            + "<h4>Company metrics parsed from SEC filings</h4>" + tbl(["Company", "Role", "Capex", "Revenue", "Debt", "Capex as of"], comp, "compact")
            + "<h4>CoreWeave debt maturity ladder (10-Q, $B)</h4>" + lad_t
            + "<h4>Where each model input came from</h4>" + tbl(["Input", "Provenance"], prov, "compact"))


# ---------------------------------------------------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------------------------------------------------
CSS = r"""
:root{--bg:#F5F6F8;--card:#fff;--ink:#0E1116;--mute:#4F5663;--line:#DEE1E7;--acc:#2D4EDD;--soft:#ECEEF2;--c1:#2D4EDD;--c2:#3B4350;--c3:#EB6834;--ok:#15803d;--bad:#b91c1c;--warn:#a16207;--link:#2D4EDD}
@media (prefers-color-scheme:dark){:root{--bg:#0C0E12;--card:#14171D;--ink:#ECEEF2;--mute:#A2A9B6;--line:#242933;--acc:#7B93FF;--soft:#1A1E26;--c1:#7B93FF;--c2:#C8CEDA;--c3:#D95926;--ok:#4ade80;--bad:#f87171;--warn:#facc15;--link:#8FA4FF}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--ink);font:18px/1.65 'Source Serif 4',Georgia,'Iowan Old Style','Times New Roman',serif;-webkit-font-smoothing:antialiased}
header.top{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);font:14px "Geist",system-ui,sans-serif}
header.top .in{max-width:1180px;margin:0 auto;padding:9px 16px;display:flex;gap:16px;align-items:center}header.top .sp{flex:1}
header.top a{color:var(--mute);text-decoration:none}header.top a:hover{color:var(--ink)}header.top b{color:var(--ink)}header.top a,header.top b,header.top button{white-space:nowrap}header.top b{overflow:hidden;text-overflow:ellipsis;min-width:0}header.top .home{display:inline-flex;align-items:center;gap:8px;color:var(--mute)}header.top .home i{font-style:normal;display:grid;place-items:center;width:26px;height:26px;background:var(--ink);color:var(--bg);border-radius:8px;font:600 11px/1 "Geist",system-ui,sans-serif;letter-spacing:.02em}header.top .div{width:1px;height:20px;background:var(--line)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px;display:grid;grid-template-columns:230px minmax(0,1fr);gap:40px}
aside.toc{position:sticky;top:58px;align-self:start;max-height:calc(100vh - 70px);overflow:auto;font:13px/1.4 "Geist",system-ui,sans-serif;padding:22px 6px 24px 0;scrollbar-width:thin}
aside.toc a{display:flex;gap:7px;color:var(--mute);text-decoration:none;padding:4px 8px;border-left:2px solid transparent;border-radius:0 6px 6px 0}
aside.toc a:hover{color:var(--ink);background:var(--soft)}
aside.toc a.active{color:var(--ink);font-weight:600;border-left-color:var(--acc);background:var(--soft)}
aside.toc .num{min-width:22px;color:var(--acc);font-variant-numeric:tabular-nums;font-weight:600}
aside.toc .grp{margin-top:16px;padding:4px 8px;font-weight:700;color:var(--ink);text-transform:uppercase;letter-spacing:.06em;font-size:11px;border-left:2px solid transparent}
aside.toc a.l3{padding-left:38px;font-size:12px}
aside.toc .subs{display:none}aside.toc .subs.open{display:block}
#prog{position:absolute;left:0;bottom:-1px;height:2px;width:0;background:var(--acc)}
.menu{display:none}
article{min-width:0;max-width:780px;padding-bottom:70px}
.titleblock{padding:46px 0 10px;border-bottom:2px solid var(--ink);margin-bottom:20px}
.kicker{font:600 12px "Geist",system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--acc)}
h1,h2,h3{font-family:"Geist",system-ui,sans-serif}h1{font-size:40px;line-height:1.08;margin:10px 0 8px;letter-spacing:-.035em;font-weight:600;text-wrap:balance}
.byline{font:15px "Geist",system-ui,sans-serif;color:var(--mute)}
.keywords{font:14px "Geist",system-ui,sans-serif;color:var(--mute);margin-top:10px}
h2{font-size:27px;font-weight:600;margin:46px 0 8px;line-height:1.18;letter-spacing:-.025em;border-top:1px solid var(--line);padding-top:26px}
h3{font-size:20px;font-weight:600;letter-spacing:-.015em;margin:30px 0 4px}h4{font:600 14px "Geist",system-ui,sans-serif;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:22px 0 6px}
p{margin:10px 0}li{margin:5px 0}a{color:var(--link)}code{font:13.5px 'Geist Mono',ui-monospace,Menlo,monospace;background:var(--soft);padding:1px 5px;border-radius:4px}
pre{overflow-x:auto;max-width:100%;background:var(--soft);padding:12px 14px;border-radius:8px;font-size:13px;line-height:1.5;margin:14px 0}pre code{background:none;padding:0;white-space:pre}
table{border-collapse:collapse;width:100%;font:14px/1.4 "Geist",system-ui,sans-serif;margin:12px 0}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-weight:600;color:var(--mute);border-bottom:2px solid var(--line)}
td.n,th.n{font-variant-numeric:tabular-nums}table.compact{font-size:13px}table.compact td:not(:first-child){font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;margin:6px 0}table.reg{min-width:760px;font-size:13px}table.reg td{padding:9px 8px}.kind{color:var(--mute);font-size:12.5px;margin-top:2px;line-height:1.35}table.reg code{font-size:12px}
.sub{color:var(--mute);font:14px "Geist",system-ui,sans-serif}
.box{border:1px solid var(--line);border-left:4px solid var(--acc);background:var(--card);padding:14px 18px;margin:20px 0;border-radius:0 10px 10px 0;font:15px/1.5 "Geist",system-ui,sans-serif}
.box h4{margin-top:0}.box.warn{border-left-color:var(--warn)}
.abstract{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 22px 14px;margin:18px 0}
.abstract h2{border:0;margin:14px 0 4px;padding:0;font-size:20px}
figure.fig{margin:26px 0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 14px 10px}
figure.fig svg{width:100%;height:auto;display:block}figure.fig svg text{fill:var(--mute);font:11px "Geist",system-ui,sans-serif}
svg .grid{stroke:var(--line);stroke-width:1}svg .whisk{stroke:var(--ink);stroke-width:1.6}svg .lab{fill:var(--ink)!important;font-weight:600}
svg .band1{fill:var(--c1);opacity:.14}svg .band2{fill:var(--c1);opacity:.28}svg .ref{stroke:var(--mute);stroke-dasharray:4 3}svg .ref.red{stroke:var(--bad)}
figcaption{font:13.5px/1.45 "Geist",system-ui,sans-serif;color:var(--mute);margin-top:6px}figcaption b{color:var(--ink)}.src{display:block;font-size:12.5px}
.srcnote{font:13px/1.45 "Geist",system-ui,sans-serif;color:var(--mute);border-left:3px solid var(--line);padding:2px 12px;margin:14px 0}
.badge{display:inline-block;padding:1px 9px;border-radius:999px;font:600 12px "Geist",system-ui,sans-serif;border:1px solid var(--line)}
.b-live{color:var(--ok);border-color:var(--ok)}.b-rec{color:var(--warn);border-color:var(--warn)}
.up{color:var(--bad)}.down{color:var(--ok)}
button{border-radius:10px;font:14px "Geist",system-ui,sans-serif;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 12px;cursor:pointer}
footer.foot{border-top:1px solid var(--line);padding:18px 0 40px;font:13px "Geist",system-ui,sans-serif;color:var(--mute)}
@media(max-width:940px){.wrap{display:block}aside.toc{display:none}h1{font-size:30px}body{font-size:16px}.menu{display:inline-block}
body.tocopen aside.toc{display:block;position:fixed;z-index:8;left:0;right:0;top:50px;bottom:0;max-height:none;background:var(--bg);padding:12px 16px 40px;overflow:auto}
body.tocopen{overflow:hidden}}
@media(max-width:620px){header.top .opt,header.top .home span,header.top .div{display:none}header.top .in{gap:10px}.titleblock{padding-top:28px}h2{font-size:23px}figure.fig{padding:10px 8px 8px}.abstract{padding:2px 14px 10px}table{font-size:13px}}
@media print{header.top,aside.toc,button{display:none!important}.wrap{display:block}body{font-size:11pt}figure,table,.box{break-inside:avoid}a{color:inherit;text-decoration:none}}
.byauthor{margin:40px 0 0;padding:22px 24px;border-radius:16px;background:var(--ink);color:var(--bg);font:15px/1.5 "Geist",system-ui,sans-serif;display:flex;flex-wrap:wrap;gap:14px 24px;align-items:center;justify-content:space-between}.byauthor b{display:block;font-size:19px;letter-spacing:-.02em;margin-bottom:2px}.byauthor span{opacity:.75}.byauthor a{display:inline-flex;align-items:center;height:42px;padding:0 18px;border-radius:10px;text-decoration:none;font-weight:600;color:var(--bg);border:1px solid color-mix(in srgb,var(--bg) 35%,transparent)}.byauthor a.p{background:var(--acc);color:var(--bg);border-color:transparent}.byauthor .row{display:flex;gap:10px;flex-wrap:wrap}
footer.foot a{color:var(--link)}
"""

LIVE_JS = r"""
const PAPER = %PAPER%;
const pct = (x, d=0) => x==null ? '–' : (100*x).toFixed(d)+'%';
const pr = x => x==null ? '–' : Math.floor(Math.round(x*1000)/10 + 0.5) + '%';   // as the paper rounds
(async () => {
  const el = document.getElementById('livebody');
  try {
    const s = await (await fetch('/api/state')).json();
    if (s.empty) throw new Error('no runs yet');
    const r = s.results, live = s.mode === 'live';
    const rows = [];
    for (const [k, name] of [['economic_bust','Economic bust'],['market_crash','Market crash']])
      for (const h of ['end-2027','end-2028','end-2029']) {
        const a = PAPER[k][h], b = r[k][h], d = (b.median - a.median) * 100;
        rows.push(`<tr><td>${name}</td><td>${h.replace('end-','End-')}</td><td class="n">${pr(a.median)} <span class="sub">(${pr(a.p10)}–${pr(a.p90)})</span></td><td class="n"><b>${pr(b.median)}</b> <span class="sub">(${pr(b.p10)}–${pr(b.p90)})</span></td><td class="n ${d>0.5?'up':d<-0.5?'down':''}">${d>=0?'+':''}${d.toFixed(1)} pts</td></tr>`);
      }
    const f = (r.expected_damage||{}).model_f || {}, pf = PAPER.f;
    rows.push(`<tr><td>Model F: neocloud fails</td><td>Part III</td><td class="n">${pct(pf.nc,1)}</td><td class="n"><b>${pct(f.p_neocloud_default,1)}</b> <span class="sub">(${f.n} draws)</span></td><td class="n sub">noisy</td></tr>`);
    rows.push(`<tr><td>Model F: expected credit losses</td><td>Part III</td><td class="n">$${pf.loss.toFixed(0)}B</td><td class="n"><b>$${(f.expected_credit_losses||0).toFixed(0)}B</b> <span class="sub">(${f.n} draws)</span></td><td class="n sub">noisy</td></tr>`);
    const src = Object.values(s.sources||{}); const ok = src.filter(x=>x.ok&&!x.stale).length, st = src.filter(x=>x.ok&&x.stale).length, bad = src.filter(x=>!x.ok).length;
    el.innerHTML = `<p><span class="badge ${live?'b-live':'b-rec'}">${live?'LIVE DATA':'RECORDED SNAPSHOT'}</span> run #${s.id}, ${new Date(s.ts).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}. Sources: ${ok} ok, ${st} stale, ${bad} failed.</p>
      <div class="scroll"><table class="compact"><thead><tr><th>Quantity</th><th>Horizon</th><th>Paper (5 Oct 2026 inputs)</th><th>This run</th><th>Change</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>
      <p class="sub">The odds in the paper's text are the 5 October calibration. This table recomputes them on the latest market, rate and filing inputs; Model G (end-customer revenue) is held at its paper calibration, and credit spreads, implied volatility and lab revenue are manual inputs. A live run uses 10,000 Model G paths, 4,000 Model D draws and 40 Model F draws, against 40,000, 10,000 and 400 in the paper, so Model F figures here are noisier. Not a forecast.</p>`;
  } catch (e) {
    el.innerHTML = '<p class="sub">Live numbers are not available in this copy of the page (' + e.message + '). The figures in the text are the paper\'s own, as of 5 October 2026.</p>';
  }
})();
"""


SPY_JS = r'''
(() => {
  const heads = [...document.querySelectorAll('article h2[id], article h3[id]')];
  const links = new Map([...document.querySelectorAll('aside.toc a[data-id]')].map(a => [a.dataset.id, a]));
  const toc = document.querySelector('aside.toc'), prog = document.getElementById('prog');
  let cur = null, tick = false;
  function update() {
    tick = false;
    let h = null;
    for (const e of heads) { if (e.getBoundingClientRect().top <= 90) h = e; else break; }
    const max = document.documentElement.scrollHeight - innerHeight;
    prog.style.width = (max > 0 ? 100 * scrollY / max : 0) + '%';
    const id = h ? h.id : null; if (id === cur) return; cur = id;
    links.forEach(a => a.classList.remove('active'));
    document.querySelectorAll('aside.toc .subs').forEach(d => d.classList.remove('open'));
    if (!h) return;
    const a = links.get(id); if (!a) return;
    a.classList.add('active');
    const nxt = a.nextElementSibling;
    const sub = a.closest('.subs') || (nxt && nxt.classList.contains('subs') ? nxt : null);
    if (sub) { sub.classList.add('open'); const parent = links.get(sub.dataset.for); if (parent && parent !== a) parent.classList.add('active'); }
    if (innerWidth > 940) { const r = a.getBoundingClientRect(), t = toc.getBoundingClientRect(); if (r.top < t.top + 20 || r.bottom > t.bottom - 20) a.scrollIntoView({block: 'center'}); }
  }
  addEventListener('scroll', () => { if (!tick) { tick = true; requestAnimationFrame(update); } }, {passive: true});
  addEventListener('resize', update); update();
  document.getElementById('menubtn').addEventListener('click', () => document.body.classList.toggle('tocopen'));
  toc.addEventListener('click', e => { if (e.target.closest('a')) document.body.classList.remove('tocopen'); });
})();
'''


def build():
    md = open(os.path.join(HERE, "working_paper.md"), encoding="utf-8").read()
    for a, b in EDITS:
        assert a in md, "edit target not found: " + a[:60]
        md = md.replace(a, b)
    # title / abstract split
    m = re.match(r"# (.+?)\n\n(.*?)\n\n## Abstract\n\n(.*?)\n\n## Part I", md, re.S)
    title, byline, abstract = m.group(1), m.group(2), m.group(3)
    body = md[m.end(3):].lstrip()
    body = "## Part I" + body[len("## Part I"):] if not body.startswith("## Part I") else body
    # chart placeholders -> figures or source notes
    fig_map = {"Model G ·": fig_fan, "Part I combined estimate": fig_odds, "Model F v2": fig_cliff, "Part III ·": lambda: fig_exceed() + fig_by_shock()}
    ph = re.compile(r"^&#91;embedded content: (.*?)\\\]\s*$", re.M)

    def sub_ph(mm):
        t = mm.group(1)
        for k, fn in fig_map.items():
            if t.startswith(k):
                return "\n\n<!--FIG-->" + fn() + "\n\n"
        return f"\n\n<div class=\"srcnote\"><b>Chart source.</b> {t}. The chart is not reproduced in this edition; the underlying run settings are listed here.</div>\n\n"
    body = ph.sub(sub_ph, body)
    body = re.sub(r"\\([~$&#<>*])", lambda x: {"~": "&#126;", "$": "&#36;", "*": "&#42;"}.get(x.group(1), x.group(1)), body)
    # split off appendix, insert new section 18 before it
    idx = body.index("## Appendix: parameters and code")
    main_md, app_md = body[:idx], body[idx:]
    table, total, cnt = register()
    sec18 = f"""
## 18. Reproducibility and simulation register

This section lists every simulation behind the paper: what kind it is, how many runs it contains, which script produced it, where the output lives and where the paper uses it. Counts come from the result files and the code constants, and this page is rebuilt from them. The figures and appendix tables below are generated, not typed.

### 18.1 What kinds of simulation were run

- **Monte Carlo over uncertain inputs (S1–S5).** Each draw samples every uncertain input from its stated distribution and produces one outcome. Model G draws revenue paths; Model D draws shortfalls, loss rates and funding conditions; pooling draws random method weights. Results are the spread over draws.
- **Agent-based simulation (S6–S10).** Model F plays 2027–29 out week by week for firm-level archetypes. Each scenario is run with a **no-shock twin** (same parameters and seed, no demand shock) and the reported outcome is the excess over the twin. With the power ceiling on, a third unconstrained run sets the ceiling, so one scenario means two or three weekly simulations.
- **Ablations (S4, S7).** Switch one mechanism on or off and compare. In Model F the same seed numbers are used across cases, but switches change random-number use, so runs are only loosely paired and small differences are noise (section 17).
- **Sweeps and tests (S8, S9, S10).** The cliff curve sweeps the shock size; the knockout test wipes out one lender at a time; the mapping run calibrates Part I's shortfall to Model F's demand shock.
- **Live recalibration (S11).** Each dashboard refresh reruns a smaller version of the whole chain on current inputs.

### 18.2 Simulation register

{{{{REGISTER}}}}

Totals. The Model F sweeps (S7–S10) comprise **{cnt['abl'] + cnt['cliff'] + cnt['ko'] + cnt['map']:,} scenario runs**: {cnt['abl']:,} ablation, {cnt['cliff']:,} cliff, {cnt['ko']:,} knockout and {cnt['map']} mapping. The Part III Model F Monte Carlo adds 1,200 more (S6). Model G and pooling use 40,000 paths each (S1, S2) and Model D 20,000 draws (S5). Together that is {total:,} Model F scenario runs, each with its own no-shock twin.

### 18.3 Reproduction check, 6 October 2026

The paper's scripts were rerun on a 2-vCPU server with Python 3.12.3, numpy 2.5.3 and scipy 1.18.1. Seeds are fixed, so Parts I and III should reproduce exactly, and they do for every combined odds figure and for Model D. Model F shows small differences even with fixed seeds, consistent with the noise noted in section 17; read them as noise.

{{{{REPRO}}}}

### 18.4 How to run it

```
bash setup.sh                                   # venv, dependencies, 10 tests, offline recorded run
python ai_bust_live.py refresh --live           # live pull (set AI_BUST_UA="Name email")
python ai_bust_probability.py --fast            # odds only, about 1.5 min
python ai_bust_probability.py                   # full run, about 9 min on 2 vCPUs
python run_abm_final.py 24                      # S7, S8, S9
python ai_bust_probability.py --calibrate-mapping   # S10
python build_site.py                            # rebuild this page
```

The dashboard runs on 127.0.0.1:8000 and is viewed over an SSH tunnel; it has no login.
"""
    appB = """
## Appendix B. Live-data pipeline and provenance

**B1. Data flow.** Fetchers pull each source, a snapshot is calibrated into model inputs with a provenance tag on every input, the models rerun (S11), and the run is stored with its snapshot in a local SQLite database that feeds the dashboard and its history chart. A source that fails falls back to the previous snapshot's value and is marked stale.

| Layer | Source | Status in the first live run |
| --- | --- | --- |
| Policy and long rates | U.S. Treasury daily par yield curve (FRED CSV as fallback) | Works |
| Equity prices, drawdowns, volatility | Stooq daily CSV (Yahoo chart API as fallback) | Stooq returns a JavaScript bot-check page (HTTP 200, no CSV); every symbol was served by Yahoo |
| Debt ladders, capex, revenue, interest, cash, leases | SEC EDGAR XBRL companyfacts | Works; one parser bug found and fixed (B2) |
| Filing dates | SEC EDGAR submissions | Works |
| Credit spreads, CDS, implied volatility, lab revenue, neocloud backlog | None free: manual_inputs.json | Manual, flagged as such |

**B2. Defect found and fixed in the first live run.** The trailing-twelve-month function took the first SEC tag with any annual data, even a tag its filer stopped using years earlier. Four values were wrong while the source still reported "ok". It now evaluates every candidate tag and keeps the one with the most recent period end.

| Company, field | Before | After |
| --- | --- | --- |
| Microsoft revenue (tag last used 2010) | $66.7B | $331.8B |
| Meta revenue (tag last used 2018) | $51.9B | $228.2B |
| Amazon capex (tag last used 2017) | $7.4B | $173.0B |
| Nvidia capex (tag last used 2020) | $0.27B | $7.4B |

The model outputs were unaffected, because the hyperscaler capex plan is set by the manual guidance input. The filings-based estimate would have been wrong had that input been removed.

**B3. Live snapshot at build time.**

{{PROV}}

**B4. What differs from the recorded snapshot.** The paper's SOX input was a 21% fall from the late-June peak, taken from news reports. The live Yahoo series, measured from its high since 1 May, shows about 10%. Both enter the market-based estimate; the live market-crash odds are lower as a result (Live update, top of page). The discrepancy has not been resolved and may reflect different peak dates or data sources.

**B5. Limits.** The ten unit tests use synthetic payloads. The Treasury, Yahoo and SEC paths have been exercised once against the real servers; there is no long-run record of their stability. The dashboard has no login and is intended for use over an SSH tunnel.
"""
    appC = f"""
## Appendix C. Simulation results in detail

Generated from the result files. Error terms are standard errors across seeds.

### C1. Model F ablation (S7)

Cells show mean excess credit losses in $B ± standard error, then the share of seeds with a neocloud failure. {ABL['n_seeds']} seeds per cell. Differences below about $10B are within noise (section 17).

{{{{ABL}}}}

### C2. Model F cliff curve (S8)

Share of seeds with a neocloud failure and mean excess credit losses, by demand shock ({CLIFF['n_seeds']} seeds per row).

{{{{CLIFF}}}}

### C3. Single-point-of-failure knockout (S9)

{{{{KO}}}}

### C4. Shock-to-outcome mapping (S10)

{{{{MAP}}}}

### C5. Model G upgrade ladder (S4)

{{{{LADDER}}}}

### C6. Model G sensitivity (S3)

{{{{TORNADO}}}}
"""
    appD = """
## Appendix D. Glossary

| Term | Meaning |
| --- | --- |
| Economic bust | End-customer AI spending falls 15% or more below the plan path at any quarter-end (section 1) |
| Market crash | The semiconductor index (SOX) falls 40% or more from a peak |
| Plan path | The revenue path that keeps pace with the AI capital stock |
| Shortfall | How far revenue falls below the plan path |
| Neocloud | A GPU-rental cloud financed largely with debt (CoreWeave is the calibration anchor) |
| No-shock twin | The same simulation with no demand shock; reported outcomes are net of it |
| Seed | The fixed starting value of a random-number generator, so a run can be repeated |
| Ablation | Switching one mechanism on or off to see what it changes |
| Cliff | The shock size at which neocloud failures become likely |
| Frozen claims | Claims tied up in legal process, not yet booked as losses |
| Log-opinion pool | A weighted average of log-odds across estimates |
| R-zone | Rapid credit growth plus high asset prices, which precede financial crises in the cited study |
"""
    appE = """
## Appendix E. References

- Greenwood, R., Shleifer, A. and You, Y. (2019). Bubbles for Fama. *Journal of Financial Economics* 131(1), 20–43.
- Greenwood, R., Hanson, S. G., Shleifer, A. and Sørensen, J. A. (2022). Predictable Financial Crises. *Journal of Finance* 77(2), 863–921.
- Battiston, S., Puliga, M., Kaushik, R., Tasca, P. and Caldarelli, G. (2012). DebtRank: Too central to fail? *Scientific Reports* 2, 541.

Market data, company disclosures, forecasts and surveys cited in the text are linked where they appear. The paper's inputs dated September and October 2026 come from the sources named in sections 1–6 and Appendix A.
"""
    appF = f"""
## Appendix F. Errata and change log

**Edition 2, {EDITION_DATE}.** The paper's analysis, numbers and conclusions are unchanged. Changes in this edition:

1. **Format.** The paper is presented as a web page with a contents list, figures generated from the result files, and cross-references. Chart placeholders from the original document were replaced by figures where the data are in the result files (Figures 1–6; Figure 6 is in Appendix C), or by a note of the run settings where they are not.
2. **Live update panel** added at the top; it shows this paper's odds beside a recalculation on live inputs.
3. **Section 18** (reproducibility and simulation register) and **Appendices B–F** added. Appendix A is the paper's original appendix.
4. **Statements updated because they were true on 30 September and are not now:**
   - Section 16.1: the live feeds have now been run once; the CoreWeave ladder is no longer a placeholder in live runs.
   - Section 17: same two points.
   - Appendix A7: measured runtime of the full probability run on a 2-vCPU server was 9 min 14 s, against the 5½ minutes stated.
   Each is marked "Updated 6 Oct 2026" in the text.
5. **Noted, not changed.** The byline is dated 30 September 2026, while several inputs are dated 2–5 October 2026. The SOX drawdown input differs from the live feed (Appendix B4). Model F re-runs differ slightly from the shipped numbers because of its run-to-run noise (section 18.3).
"""
    app_md = app_md.replace("## Appendix: parameters and code", "## Appendix A. Parameters and code")
    full_md = main_md + sec18 + "\n\n" + app_md + appB + appC + appD + appE + appF
    # code fences need fenced_code
    ext = ["tables", "fenced_code", "sane_lists"]
    h = markdown.markdown(full_md, extensions=ext)
    # heading ids
    toc = []

    def hid(mm):
        lvl, txt = mm.group(1), mm.group(2)
        plain = re.sub(r"<[^>]+>", "", txt)
        n = re.match(r"(\d+(?:\.\d+)?[a-z]?)\.?\s", plain)
        if n:
            i = "sec-" + n.group(1).replace(".", "-")
        elif plain.startswith("Appendix "):
            i = "app-" + plain.split()[1].rstrip(".").lower()
        elif plain.startswith("Part "):
            i = "part-" + plain.split()[1].lower()
        else:
            i = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
        toc.append((int(lvl), i, plain))
        return f'<h{lvl} id="{i}">{txt}</h{lvl}>'
    h = re.sub(r"<h([23])>(.*?)</h\1>", hid, h)
    ids = {t[1] for t in toc}

    def link_num(mm):
        num = mm.group(0)
        i = "sec-" + num.replace(".", "-")
        return f'<a href="#{i}">{num}</a>' if i in ids else num

    def xref(mm):
        return mm.group(1) + re.sub(r"\d+(?:\.\d+)?[a-z]?", link_num, mm.group(2))
    h = re.sub(r"(\bsections? )(\d+(?:\.\d+)?[a-z]?(?:(?: and |, | to |–)\d+(?:\.\d+)?[a-z]?)*)", xref, h)
    h = h.replace("<table>", '<div class="scroll"><table>').replace("</table>", "</table></div>")
    # placeholders
    repl = {"{{REGISTER}}": table, "{{REPRO}}": repro_html(), "{{PROV}}": provenance_html(), "{{ABL}}": ablation_html(), "{{CLIFF}}": cliff_html(),
            "{{KO}}": knockout_html(), "{{MAP}}": mapping_html(), "{{LADDER}}": ladder_html(), "{{TORNADO}}": fig_tornado()}
    for k, v in repl.items():
        h = re.sub(r"<p>" + re.escape(k) + r"</p>", lambda _: v, h)
        h = h.replace(k, v)
    h = h.replace("<!--FIG-->", "")
    h = re.sub(r"<p>(<figure)", r"\1", h)
    h = re.sub(r"(</figure>)</p>", r"\1", h)
    h = re.sub(r"<p>(<div class=\"srcnote\">)", r"\1", h)
    h = re.sub(r"(</div>)</p>", r"\1", h)
    # sidebar: parts as group headings, sections as numbered links, subsections shown only for the active section
    t, open_sub = [], False
    for lvl, i, txt in toc:
        if lvl == 2:
            if open_sub:
                t.append("</div>")
                open_sub = False
            if txt.startswith("Part "):
                t.append(f'<a class="grp" href="#{i}">{esc(re.sub(r"^Part (\w+) — ", r"Part \1 · ", txt))}</a>')
                continue
            mm = re.match(r"(\d+)\.\s+(.*)", txt) or re.match(r"Appendix ([A-Z])\.\s+(.*)", txt)
            num, ttl = (mm.group(1), mm.group(2)) if mm else ("", txt)
            t.append(f'<a class="l2" data-id="{i}" href="#{i}"><span class="num">{num}</span><span>{esc(ttl)}</span></a><div class="subs" data-for="{i}">')
            open_sub = True
        elif lvl == 3 and open_sub:
            t.append(f'<a class="l3" data-id="{i}" href="#{i}">{esc(txt)}</a>')
    if open_sub:
        t.append("</div>")
    tocs = "\n".join(t)
    paper_js = json.dumps({"economic_bust": {k: {x: PR["economic_bust"][k]["combined"][x] for x in ("median", "p10", "p90")} for k in PR["economic_bust"]},
                           "market_crash": {k: {x: PR["market_crash"][k]["combined"][x] for x in ("median", "p10", "p90")} for k in PR["market_crash"]},
                           "f": {"nc": PR["expected_damage"]["model_f"]["p_neocloud_default"], "loss": PR["expected_damage"]["model_f"]["expected_credit_losses"]}})
    abs_html = markdown.markdown(abstract, extensions=["tables"]).replace("<table>", '<div class="scroll"><table>').replace("</table>", "</table></div>")
    abs_html = re.sub(r"\\([~$])", lambda x: "&#126;" if x.group(1) == "~" else "&#36;", abs_html)
    abs_html = abs_html.replace("\\~", "~")
    byl = re.sub(r"@", "", byline.split("·")[-1]).strip()
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>When the Buildout Breaks: how likely is an AI bust, and how bad would it be?</title>
<meta name="description" content="A working paper on the probability and damage of an AI investment bust: four pooled estimates of the odds, two damage models, full methods and code. Not investment advice.">
<link rel="canonical" href="https://aibust.ykhalil.com/paper"><meta name="color-scheme" content="light dark">
<meta property="og:type" content="article"><meta property="og:site_name" content="AI Bust Odds"><meta property="og:title" content="When the Buildout Breaks: how likely is an AI bust, and how bad would it be?">
<meta property="og:description" content="Four pooled estimates of the odds, two damage models, full methods and code. A working paper by Yassin Khalil. Not investment advice."><meta property="og:url" content="https://aibust.ykhalil.com/paper">
<meta property="og:image" content="https://aibust.ykhalil.com/assets/aibust-og.png"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="preload" href="/assets/fonts/geist.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/source-serif-4-normal.woff2" as="font" type="font/woff2" crossorigin><link rel="stylesheet" href="/assets/fonts.css">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"ScholarlyArticle","headline":"When the Buildout Breaks: How Likely Is an AI Bust, and How Bad Would It Be?","url":"https://aibust.ykhalil.com/paper","datePublished":"2026-09-30","inLanguage":"en","isAccessibleForFree":true,"author":{{"@type":"Person","name":"Yassin Khalil","url":"https://ykhalil.com/","sameAs":["https://www.linkedin.com/in/yassin-khalil/","https://github.com/YassinKhalil"]}},"codeRepository":"https://github.com/YassinKhalil/when-the-buildout-breaks","keywords":"AI investment boom, financial stability, crash probability, contagion, agent-based model, credit risk"}}</script>
<style>{CSS}</style></head><body>
<header class="top"><div class="in"><button class="menu" id="menubtn" aria-label="Contents">☰ Contents</button><a class="home" href="https://ykhalil.com/" aria-label="Yassin Khalil, home"><i>YK</i><span>ykhalil.com</span></a><span class="div"></span><b>When the Buildout Breaks</b><a class="opt" href="#live">Live update</a><a class="opt" href="#sec-18">Simulations</a><a class="opt" href="#app-a">Appendices</a><span class="sp"></span><a href="/">Live dashboard</a><a class="opt" href="/open-source/">Open source</a><button class="opt" onclick="window.print()">Print / PDF</button></div><div id="prog"></div></header>
<div class="wrap"><aside class="toc"><a href="#top"><b>Abstract</b></a><a href="#live">Live update</a>{tocs}</aside>
<article id="top">
<div class="titleblock"><div class="kicker">Working paper · Edition 2 · {EDITION_DATE}</div><h1>{esc(title)}</h1>
<div class="byline">{esc(byl)} · Original draft 30 September 2026 · Data as of 5 October 2026<br>Written by Claude (Anthropic); see the disclosure in <a href="#sec-17">section 17</a>.</div>
<div class="keywords"><b>Keywords:</b> AI investment boom · financial stability · crash probability · contagion · agent-based model · credit risk</div></div>
<div class="box warn"><b>Not investment advice.</b> These are model estimates for analysis, resting on stated judgment calls. They are not forecasts or recommendations.</div>
<div class="abstract"><h2>Abstract</h2>{abs_html}</div>
<div class="box" id="live"><h4>Live update</h4><div id="livebody"><p class="sub">Loading live numbers…</p></div></div>
{h}
<aside class="byauthor" aria-label="About the author"><div><b>Written at the direction of Yassin Khalil</b><span>I build software, automation and data tools for founders.</span></div><div class="row"><a class="p" href="https://ykhalil.com/">See my work</a><a href="https://www.linkedin.com/in/yassin-khalil/" rel="noopener">LinkedIn</a><a href="https://github.com/YassinKhalil/when-the-buildout-breaks" rel="noopener">Code</a></div></aside>
<footer class="foot">When the Buildout Breaks · Edition 2, {EDITION_DATE} · Generated by build_site.py from working_paper.md and the result files · Not investment advice. Built by <a href="https://ykhalil.com/">Yassin Khalil</a>.</footer>
</article></div>
<script>{LIVE_JS.replace('%PAPER%', paper_js)}{SPY_JS}</script></body></html>"""
    open(os.path.join(HERE, "paper.html"), "w", encoding="utf-8").write(page)
    print("paper.html", len(page), "bytes;", len(FIGS), "figures;", len(toc), "headings")


if __name__ == "__main__":
    build()
