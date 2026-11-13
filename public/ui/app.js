// Executive overview for the AI-bust paper. Reads the static files written by scripts/run_pipeline.py:
//   /data/latest_run.json      metrics, histograms and density curves (all simulation happens in Python, never in the browser)
//   /data/historical_risk.csv  one row per night
// The "deduction engine" below turns VaR/CVaR numbers into ratings and sentences. Thresholds are in one place on purpose.

const $ = (s, r = document) => r.querySelector(s);
const el = (tag, attrs = {}, html = "") => { const e = document.createElement(tag); for (const k in attrs) e.setAttribute(k, attrs[k]); e.innerHTML = html; return e; };
const NS = "http://www.w3.org/2000/svg";
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------------------------------------------------------
// Deduction engine: thresholds (upper bounds, exclusive) for LOW / MODERATE / HIGH, everything above is CRITICAL.
// ---------------------------------------------------------------------------------------------------------------
const THRESHOLDS = {
  contagion: { cvar: [10, 50, 250], base: [10, 50, 250], unit: "$B" },            // Model D credit loss, USD bn
  equity:    { cvar: [0.20, 0.35, 0.55], base: [0.20, 0.35, 0.55], unit: "%" },   // SMH drawdown
  sovereign: { cvar: [25, 100, 200], base: [25, 100, 200], unit: "$B" },          // sovereign rescue spend, USD bn
};
const LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"];
const rate = (x, cuts) => LEVELS[cuts.findIndex(c => x < c) === -1 ? 3 : cuts.findIndex(c => x < c)];

const usd = (b, d) => { const a = Math.abs(b); if (a >= 1000) return "$" + (b / 1000).toFixed(2) + "T"; if (a >= 100 || d === 0) return "$" + Math.round(b) + "B"; if (a >= 10) return "$" + b.toFixed(0) + "B"; return "$" + b.toFixed(1) + "B"; };
const pc = (x, d = 0) => (100 * x).toFixed(d) + "%";
const px = x => "$" + x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const px0 = x => "$" + Math.round(x).toLocaleString("en-US");

function deduce(run) {
  const d = run.model_d, f = run.model_f, T = THRESHOLDS;
  const cl = d.credit_loss, smh = f.smh_drawdown, sov = f.sovereign_spend, spy = f.spy_drawdown;
  const sm = run.inputs.smh, sp = run.inputs.spy;
  return [
    { key: "contagion", title: "Systemic Contagion Risk", tail: rate(cl.cvar95, T.contagion.cvar), base: rate(cl.ev, T.contagion.base),
      text: `In the worst 5% of futures, credit losses across lenders average <b>${usd(cl.cvar95)}</b> (VaR95 ${usd(cl.var95)}). The base case is <b>${usd(cl.ev)}</b>; the mean, which weights the tail, is ${usd(cl.mean)}.`,
      extra: `A neocloud fails in ${pc(d.p_neocloud_default)} of futures, a frontier lab in ${pc(d.p_lab_default)}, and a bank in ${pc(d.p_bank_default, 1)}.`, baseTxt: usd(cl.ev) },
    { key: "equity", title: "Semiconductor Drawdown Risk", tail: rate(smh.cvar95, T.equity.cvar), base: rate(smh.ev, T.equity.base),
      text: `The base case takes SMH down <b>${pc(smh.ev)}</b>; the worst 5% of futures average <b>${pc(smh.cvar95)}</b>. SPY: ${pc(spy.ev)} base case, ${pc(spy.cvar95)} in the tail.`,
      extra: sm ? `SMH is already ${pc(sm.drawdown_from_peak)} below its May peak.` : "", baseTxt: pc(smh.ev) },
    { key: "sovereign", title: "Sovereign Rescue Pressure", tail: rate(sov.cvar95, T.sovereign.cvar), base: rate(sov.ev, T.sovereign.base),
      text: `Governments spend <b>${usd(sov.ev)}</b> in the base case and an average <b>${usd(sov.cvar95)}</b> in the worst 5% of futures, to keep critical AI compute and lenders alive.`,
      extra: `No rescue is needed in ${pc(sov.p_zero)} of simulated futures.`, baseTxt: usd(sov.ev) },
  ];
}

// ---------------------------------------------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------------------------------------------
async function load() {
  const [run, csv] = await Promise.all([
    fetch("/data/latest_run.json", { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error("latest_run.json " + r.status); return r.json(); }),
    fetch("/data/historical_risk.csv", { cache: "no-cache" }).then(r => r.ok ? r.text() : "").catch(() => ""),
  ]);
  const lines = csv.trim().split("\n"); const head = (lines.shift() || "").split(",");
  const hist = lines.filter(Boolean).map(l => { const c = l.split(","), o = {}; head.forEach((h, i) => o[h] = h === "date" ? c[i] : (c[i] === "" ? null : +c[i])); return o; });
  return { run, hist };
}

// ---------------------------------------------------------------------------------------------------------------
// SVG helpers
// ---------------------------------------------------------------------------------------------------------------
function svgEl(tag, attrs = {}, text) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; }
function niceTicks(lo, hi, n = 5) {
  const span = hi - lo, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * mag; const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
const tip = $("#tip");
function showTip(html, x, y) { tip.innerHTML = html; tip.hidden = false; const w = tip.offsetWidth; tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, x + 14)) + "px"; tip.style.top = Math.max(8, y - 44) + "px"; }
const hideTip = () => { tip.hidden = true; };

// Density (area) or bar-histogram chart with the EV / VaR / CVaR markers. `m` is a metrics block from latest_run.json.
function distChart(host, m, o) {
  const narrow = innerWidth < 700, W = o.W || (narrow ? 520 : 960), H = o.H || (narrow ? 420 : 400), L = 52, R = 22, T = 30, B = 44;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" });
  host.replaceChildren(svg);
  const xs = m.curve.x, ys = m.curve.y, x0 = xs[0], x1 = xs[xs.length - 1];
  const X = v => L + (Math.min(Math.max(v, x0), x1) - x0) / (x1 - x0) * (W - L - R);
  // The mass sitting at ~0 (no bust) can dwarf the rest; clip the y axis to the body of the distribution and say so.
  const nb = m.histogram.counts.length, edges = m.histogram.edges, total = m.n;
  const firstShare = m.histogram.counts[0] / total;
  const rest = Math.max(...ys.filter((_, i) => xs[i] > edges[3]), 1e-12);
  const ymaxAll = Math.max(...ys);
  const clipped = ymaxAll > rest * 2.2;
  const ymax = (clipped ? rest : ymaxAll) * 1.18;
  const Y = v => T + (1 - Math.min(v, ymax) / ymax) * (H - T - B);
  // grid + x ticks
  for (const t of niceTicks(x0, x1, W < 700 ? 4 : 6)) { const x = X(t); svg.append(svgEl("line", { class: "grid", x1: x, x2: x, y1: T, y2: H - B }), svgEl("text", { x, y: H - B + 18, "text-anchor": "middle" }, o.fmt(t))); }
  svg.append(svgEl("line", { class: "axis", x1: L, x2: W - R, y1: H - B, y2: H - B }));
  svg.append(svgEl("text", { x: L, y: H - 6 }, o.xlabel));
  svg.append(svgEl("text", { x: 4, y: 12 }, "likelihood"));
  if (o.bars) {
    const n = m.histogram.counts, mx = Math.max(...(clipped ? n.slice(1) : n), 1) * (clipped ? 1.15 : 1.1);
    n.forEach((c, i) => { const a = X(edges[i]), b = X(edges[i + 1]); const h = Math.min(c, mx) / mx * (H - T - B); const inTail = edges[i] >= m.var95;
      svg.append(svgEl("rect", { x: a + 0.5, y: H - B - h, width: Math.max(1, b - a - 1), height: h, fill: inTail ? "var(--bad)" : "var(--acc)", "fill-opacity": inTail ? .55 : .4 })); });
  } else {
    let path = `M${X(xs[0])},${Y(0)}`; xs.forEach((x, i) => path += ` L${X(x)},${Y(ys[i])}`); path += ` L${X(x1)},${Y(0)} Z`;
    svg.append(svgEl("path", { class: "area", d: path }));
    // shaded tail beyond VaR95
    const ti = xs.map((x, i) => [x, ys[i]]).filter(([x]) => x >= m.var95);
    if (ti.length > 1) { let p = `M${X(ti[0][0])},${Y(0)}`; ti.forEach(([x, y]) => p += ` L${X(x)},${Y(y)}`); p += ` L${X(ti[ti.length - 1][0])},${Y(0)} Z`; svg.append(svgEl("path", { class: "tailarea", d: p })); }
  }
  if (clipped) {
    const bx = X(xs[0]) + 4;
    svg.append(svgEl("line", { class: "brk", x1: bx - 6, x2: bx + 22, y1: T + 74, y2: T + 64 }));
    svg.append(svgEl("text", { x: bx + 30, y: T + 68, class: "mt" }, `${pc(firstShare)} of draws sit at or below ${o.fmt(edges[1])} (bar cut off)`));
  }
  // markers with staggered labels so they never collide
  const marks = [["ev", m.ev, "Base case (median)", "mk-ev"], ["var", m.var95, "VaR 95%", "mk-var"], ["cvar", m.cvar95, "CVaR 95%", "mk-cvar"]];
  marks.forEach(([k, v, name, cls], i) => {
    const x = X(v), off = v > x1;
    svg.append(svgEl("line", { class: cls, x1: x, x2: x, y1: T - 4, y2: H - B }));
    const anchorEnd = x > W - 150;
    svg.append(svgEl("text", { x: anchorEnd ? x - 6 : x + 6, y: T + 4 + i * 15, class: "mt", "text-anchor": anchorEnd ? "end" : "start" }, `${name}: ${o.fmt(v)}${off ? " →" : ""}`));
  });
  // hover: cursor + tooltip with the exceedance probability at x
  const cursor = svgEl("line", { class: "cursor", y1: T, y2: H - B, visibility: "hidden" }); svg.append(cursor);
  const hit = svgEl("rect", { class: "hit", x: L, y: T, width: W - L - R, height: H - T - B }); svg.append(hit);
  const move = ev => { const r = svg.getBoundingClientRect(), t = ev.touches ? ev.touches[0] : ev; const sx = (t.clientX - r.left) / r.width * W;
    const v = x0 + (sx - L) / (W - L - R) * (x1 - x0); if (v < x0 || v > x1) return hideTip();
    cursor.setAttribute("x1", sx); cursor.setAttribute("x2", sx); cursor.setAttribute("visibility", "visible");
    const ex = exceed(m, v); showTip(`<b>${o.fmt(v)}</b><br>${pc(ex, ex < .1 ? 1 : 0)} of futures are worse than this`, t.clientX, t.clientY); };
  hit.addEventListener("mousemove", move); hit.addEventListener("touchstart", move, { passive: true }); hit.addEventListener("touchmove", move, { passive: true });
  hit.addEventListener("mouseleave", () => { hideTip(); cursor.setAttribute("visibility", "hidden"); });
}
// P(outcome > v), interpolated from the histogram (plus overflow beyond the last edge)
function exceed(m, v) {
  const e = m.histogram.edges, c = m.histogram.counts; let above = m.histogram.overflow;
  for (let i = 0; i < c.length; i++) { if (e[i] >= v) above += c[i]; else if (e[i + 1] > v) above += c[i] * (e[i + 1] - v) / (e[i + 1] - e[i]); }
  return above / m.n;
}

// ---------------------------------------------------------------------------------------------------------------
// Overview sections
// ---------------------------------------------------------------------------------------------------------------
const MEASURES = [
  { id: "credit", label: "Credit losses", get: r => r.model_d.credit_loss, fmt: v => usd(v, 0), xlabel: "Total credit loss to lenders, $ billions (Model D)", noun: "credit losses" },
  { id: "smh", label: "SMH drawdown", get: r => r.model_f.smh_drawdown, fmt: v => pc(v), xlabel: "Fall in the semiconductor ETF from today's level (Model F)", noun: "SMH drawdown" },
  { id: "spy", label: "SPY drawdown", get: r => r.model_f.spy_drawdown, fmt: v => pc(v), xlabel: "Fall in the broad market from today's level (Model F)", noun: "SPY drawdown" },
  { id: "sov", label: "Sovereign rescue", get: r => r.model_f.sovereign_spend, fmt: v => usd(v, 0), xlabel: "Government rescue spend, $ billions (Model F)", noun: "rescue spend" },
];

function renderKpis(run) {
  const e = run.odds.economic_bust["end-2028"], c = run.odds.market_crash["end-2028"], cl = run.model_d.credit_loss;
  const k = [
    [pc(e.median), "Economic bust by end-2028", `10th–90th pct ${pc(e.p10)}–${pc(e.p90)}`],
    [pc(c.median), "Chip-stock crash (SOX −40%) by end-2028", `10th–90th pct ${pc(c.p10)}–${pc(c.p90)}`],
    [usd(cl.mean), "Expected credit losses (mean)", `base case ${usd(cl.ev)}, tail avg ${usd(cl.cvar95)}`],
    [pc(run.model_d.p_neocloud_default), "Chance a neocloud fails", `frontier lab ${pc(run.model_d.p_lab_default)}, bank ${pc(run.model_d.p_bank_default, 1)}`],
  ];
  $("#kpis").innerHTML = k.map(([v, l, r]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="r">${r}</div></div>`).join("");
}

function renderRatings(run) {
  $("#ratings").innerHTML = deduce(run).map(d => `
    <article class="rate lv-${d.tail}"><h3>${d.title}</h3>
      <span class="pill">${d.tail}</span>
      <p>${d.text}</p><p>${d.extra}</p>
      <p class="base lv-${d.base}">Base case: <b style="color:var(--c)">${d.base}</b> (${d.baseTxt})</p></article>`).join("");
}

function renderHero(run) {
  const tabs = $("#measure-tabs"); let cur = MEASURES[0];
  const draw = () => {
    const m = cur.get(run);
    distChart($("#hero-chart"), m, { fmt: cur.fmt, xlabel: cur.xlabel });
    $("#dist-sub").textContent = `${run.n_draws.toLocaleString()} simulated futures. Hover the chart to see how likely a worse outcome is.`;
    $("#hero-legend").innerHTML = `<li><i style="border-color:var(--ev);border-top-style:dashed"></i>Base case = median</li><li><i style="border-color:var(--tail);border-top-style:dotted"></i>VaR 95%: 1 in 20 futures is worse</li><li><i style="border-color:var(--bad)"></i>CVaR 95%: average of those worst 5%</li><li><i class="sw" style="background:var(--bad);opacity:.4"></i>Tail beyond VaR</li>`;
    $("#hero-read").innerHTML = `Half of simulated futures end below <b>${cur.fmt(m.ev)}</b> of ${cur.noun}, but the distribution is not a bell: ${pc(m.p_zero)} of futures show essentially none (no bust) and a second hump holds the busts. The worst 5% average <b>${cur.fmt(m.cvar95)}</b>.`;
    $("#hero-chart").setAttribute("aria-label", `Density chart of ${cur.noun}. Base case ${cur.fmt(m.ev)}, VaR95 ${cur.fmt(m.var95)}, CVaR95 ${cur.fmt(m.cvar95)}.`);
  };
  MEASURES.forEach(ms => { const b = el("button", { role: "tab", "aria-selected": ms === cur, tabindex: ms === cur ? 0 : -1 }, ms.label); b.onclick = () => select(ms, b); ms.btn = b; tabs.append(b); });
  const select = (ms, b) => { cur = ms; MEASURES.forEach(x => { x.btn.setAttribute("aria-selected", x === ms); x.btn.tabIndex = x === ms ? 0 : -1; }); draw(); };
  tabs.addEventListener("keydown", e => { const i = MEASURES.indexOf(cur); const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null; if (n == null) return; const t = MEASURES[(n + MEASURES.length) % MEASURES.length]; select(t); t.btn.focus(); });
  draw(); let w = innerWidth; addEventListener("resize", () => { if (Math.abs(innerWidth - w) > 40) { w = innerWidth; draw(); } });
}

function renderTargets(run) {
  const cards = [["SPY", "S&P 500 ETF", run.inputs.spy, run.model_f.spy_drawdown, "var(--acc)"], ["SMH", "Semiconductor ETF", run.inputs.smh, run.model_f.smh_drawdown, "var(--tail)"]];
  $("#targets-body").innerHTML = cards.map(([sym, name, inp, dd]) => {
    if (!inp || !inp.price) return `<div class="tgt"><h3>${sym}</h3><p class="sub">No live price in this run.</p></div>`;
    const P = inp.price, lv = [["Base case", dd.ev], ["Mean", dd.mean], ["VaR 95%", dd.var95], ["CVaR 95%", dd.cvar95]];
    const worst = Math.max(...lv.map(x => x[1]));
    return `<div class="tgt"><h3>${sym} <span class="sub">${name}</span></h3><div class="now">Last close ${px(P)} (${inp.date})</div>
      <p class="base-line">Base case implies ${sym} retraces to <b>${px0(P * (1 - dd.ev))}</b> (${pc(-dd.ev)}). In the tail it averages <b>${px0(P * (1 - dd.cvar95))}</b> (${pc(-dd.cvar95)}).</p>
      <div class="ladder">${lv.map(([n, d], i) => `<div class="rung"><span>${n}</span><span class="bar"><i style="width:${Math.max(2, d / worst * 100)}%;--c:${i === 3 ? "var(--bad)" : i === 2 ? "var(--tail)" : "var(--acc)"}"></i></span><span class="n"><b>${px0(P * (1 - d))}</b> <span class="sub">${pc(-d)}</span></span></div>`).join("")}</div></div>`;
  }).join("");
}

function lineChart(host, rows, series, W = innerWidth < 700 ? 520 : 960, H = innerWidth < 700 ? 320 : 280) {
  const L = 54, R = 20, T = 18, B = 34, svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` }); host.replaceChildren(svg);
  const t = rows.map(r => Date.parse(r.date)), t0 = Math.min(...t), t1 = Math.max(...t, t0 + 864e5 * 6);
  const vals = rows.flatMap(r => series.map(s => r[s.key])).filter(v => v != null), hi = Math.max(...vals) * 1.1, lo = 0;
  const X = v => L + (v - t0) / (t1 - t0) * (W - L - R), Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  for (const g of niceTicks(lo, hi, 4)) svg.append(svgEl("line", { class: "grid", x1: L, x2: W - R, y1: Y(g), y2: Y(g) }), svgEl("text", { x: L - 8, y: Y(g) + 4, "text-anchor": "end" }, series[0].fmt(g)));
  const days = Math.round((t1 - t0) / 864e5), step = Math.max(1, Math.ceil(days / 6));
  for (let d = 0; d <= days; d += step) { const v = t0 + d * 864e5; svg.append(svgEl("text", { x: X(v), y: H - 10, "text-anchor": "middle" }, new Date(v).toLocaleDateString("en", { month: "short", day: "numeric", timeZone: "UTC" }))); }
  series.forEach(s => {
    const pts = rows.filter(r => r[s.key] != null).map(r => [X(Date.parse(r.date)), Y(r[s.key]), r]);
    if (pts.length > 1) svg.append(svgEl("path", { d: "M" + pts.map(p => p[0] + "," + p[1]).join(" L"), fill: "none", stroke: s.color, "stroke-width": 2.4, "stroke-linejoin": "round" }));
    pts.forEach(([x, y, r]) => { const c = svgEl("circle", { cx: x, cy: y, r: pts.length === 1 ? 6 : 3.5, fill: s.color, tabindex: 0 });
      const show = e => { const b = c.getBoundingClientRect(); showTip(`<b>${r.date}</b><br>${s.label}: ${s.fmt(r[s.key])}`, e.clientX || b.x, e.clientY || b.y); };
      c.addEventListener("mousemove", show); c.addEventListener("focus", show); c.addEventListener("mouseleave", hideTip); c.addEventListener("blur", hideTip); svg.append(c); });
  });
}
function renderHistory(hist) {
  const sub = $("#hist-sub"), host = $("#hist-chart");
  const series = [{ key: "d_credit_ev_bn", label: "Credit loss, base case", color: "var(--acc)", fmt: v => usd(v, 0) }, { key: "d_credit_cvar95_bn", label: "Credit loss, CVaR 95%", color: "var(--bad)", fmt: v => usd(v, 0) }];
  $("#hist-legend").innerHTML = series.map(s => `<li><i style="border-color:${s.color}"></i>${s.label}</li>`).join("");
  sub.textContent = hist.length > 1 ? `Model D credit losses, one point per nightly run (${hist.length} runs).` : "The pipeline appends one point a night, so this chart fills in over the coming days.";
  lineChart(host, hist, series);
}

function renderInputs(run) {
  const i = run.inputs, pv = i.provenance || {}, live = k => (pv[k] || "").startsWith("feed");
  const tile = (l, v, ok, src) => `<div class="inp"><div class="l">${l}</div><div class="v">${v}</div><span class="badge ${ok ? "b-live" : "b-fallback"}">${ok ? "live feed" : "paper default"}</span>${src ? `<div class="sub" style="font-size:12px;margin-top:4px">${src}</div>` : ""}</div>`;
  const s = i.sources || {};
  $("#inputs-body").innerHTML = [
    tile("SPY close", i.spy && i.spy.price ? px(i.spy.price) : "–", !!(i.spy && i.spy.price), "Yahoo Finance"),
    tile("SMH close", i.smh && i.smh.price ? px(i.smh.price) : "–", !!(i.smh && i.smh.price), i.smh ? `${pc(i.smh.drawdown_from_peak)} below May peak` : ""),
    tile("SMH volatility", i.smh ? pc(i.smh.iv30 || i.smh.rv30) : "–", !!i.smh, i.smh && i.smh.iv30 ? "option-implied, 30 day" : "realised, 30 day (no usable option quotes)"),
    tile("High-yield spread", i.hy_oas_bps ? i.hy_oas_bps + " bp" : "–", i.hy_oas_bps != null, i.hy_oas_paper_ref_bps ? `${i.hy_oas_bps - i.hy_oas_paper_ref_bps >= 0 ? "+" : ""}${i.hy_oas_bps - i.hy_oas_paper_ref_bps} bp vs the paper's 5 Oct inputs (FRED)` : "FRED"),
  ].join("");
}

// ---------------------------------------------------------------------------------------------------------------
// Deep dive
// ---------------------------------------------------------------------------------------------------------------
function metricRow(name, m, f) { return `<tr><td>${name}</td><td>${f(m.ev)}</td><td>${f(m.mean)}</td><td>${f(m.p90)}</td><td>${f(m.var95)}</td><td>${f(m.cvar95)}</td><td>${f(m.max)}</td></tr>`; }
function renderMC(run) {
  const host = $("#p-mc");
  const defs = [["Credit losses, $B (Model D)", run.model_d.credit_loss, v => usd(v, 0)], ["SMH drawdown (Model F)", run.model_f.smh_drawdown, v => pc(v)],
    ["SPY drawdown (Model F)", run.model_f.spy_drawdown, v => pc(v)], ["Sovereign rescue spend, $B (Model F)", run.model_f.sovereign_spend, v => usd(v, 0)]];
  host.innerHTML = `<div class="card"><h2>Simulation results</h2><p class="sub">${run.n_draws.toLocaleString()} draws per model, seed ${run.seed}, engine time ${run.runtime_s.engine}s. Red bars are the worst 5%.</p>
    <div class="minis" id="minis"></div>
    <h3 class="panel-h">Risk metrics</h3><div class="scroll"><table><thead><tr><th>Measure</th><th>EV (median)</th><th>Mean</th><th>P90</th><th>VaR 95%</th><th>CVaR 95%</th><th>Worst draw</th></tr></thead><tbody>
    ${defs.map(([n, m, f]) => metricRow(n, m, f)).join("")}</tbody></table></div>
    <h3 class="panel-h">Odds feeding the shocks</h3>${oddsTable(run)}
    <h3 class="panel-h">How closely does the Model F emulator track the real agent-based model?</h3>${emuTable(run)}</div>`;
  const minis = $("#minis", host);
  defs.forEach(([n, m, f]) => { const d = el("div", { class: "mini" }, `<h3>${n}</h3><div class="chart"></div>`); minis.append(d); distChart($(".chart", d), m, { fmt: f, xlabel: "", bars: true, W: 520, H: 280 }); });
}
function oddsTable(run) {
  const o = run.odds, hs = ["end-2027", "end-2028", "end-2029"];
  const row = (n, k) => `<tr><td>${n}</td>${hs.map(h => `<td>${pc(o[k][h].median)} <span class="sub">(${pc(o[k][h].p10)}–${pc(o[k][h].p90)})</span></td>`).join("")}</tr>`;
  return `<div class="scroll"><table><thead><tr><th>Cumulative odds, median (10th–90th)</th><th>End-2027</th><th>End-2028</th><th>End-2029</th></tr></thead><tbody>${row("Economic bust", "economic_bust")}${row("Market crash", "market_crash")}</tbody></table></div>`;
}
function emuTable(run) {
  const v = run.model_f.emulator.validation_5fold, names = { sp500_dd: "Broad index drawdown", ai_dd: "AI index drawdown (SMH proxy)", credit_loss: "Credit loss ($B)", sov_spend: "Sovereign spend ($B)" };
  return `<div class="scroll"><table><thead><tr><th>Output</th><th>Held-out R²</th><th>Mean: ABM</th><th>Mean: emulator</th><th>95th pct: ABM</th><th>95th pct: emulator</th></tr></thead><tbody>
  ${Object.entries(v).map(([k, x]) => `<tr><td>${names[k] || k}</td><td>${x.r2_heldout}</td><td>${x.mean_real}</td><td>${x.mean_emulated}</td><td>${x.p95_real}</td><td>${x.p95_emulated}</td></tr>`).join("")}</tbody></table></div>
  <p class="sub">Fitted on ${run.model_f.emulator.n_training_runs} real runs of the agent-based model, scored on runs it had not seen (5-fold cross-validation). Credit loss is the weakest output; the headline tail metrics use Model D's exact network for credit losses.</p>`;
}
function renderMethod(run) {
  const pv = run.inputs.provenance || {}, T = THRESHOLDS;
  $("#p-method").innerHTML = `<div class="card prose"><h2>How the numbers are made</h2>
  <p>Every night a Python pipeline pulls live prices and credit spreads, re-pools the paper's four odds methods, then runs <b>${run.n_draws.toLocaleString()}</b> draws of each damage model. Each draw samples a demand shortfall from the pooled odds and the uncertain model parameters, and produces a continuous outcome in dollars or percent. The browser only reads the finished results.</p>
  <h3>Model D: contagion network</h3><p>Twelve sectors linked by spending and credit claims; a demand shock propagates through revenue, funding and loss channels over twelve rounds. Vectorised with numpy across draws and parallelised with joblib; the code is tested draw by draw against the original scalar model.</p>
  <h3>Model F: agent-based model, emulated</h3><p>The weekly agent-based model takes about a second per draw, so 10,000 draws are produced by a regression emulator fitted to ${run.model_f.emulator.n_training_runs} real runs. It keeps the model's noise and the correlation between outputs. SMH drawdown is the model's AI-index drawdown; SPY drawdown is its synthetic broad index.</p>
  <h3>Input provenance</h3><ul>${Object.entries(pv).map(([k, v]) => `<li><b>${esc(k)}</b>: ${esc(v)}</li>`).join("")}</ul>
  <h3>Rating thresholds</h3><p>Ratings compare the worst-5% average (CVaR 95%) with fixed cut-offs. Below the first is LOW, then MODERATE, HIGH, and above the last CRITICAL.</p>
  <div class="scroll"><table><thead><tr><th>Measure</th><th>LOW below</th><th>MODERATE below</th><th>HIGH below</th></tr></thead><tbody>
  <tr><td>Credit losses</td>${T.contagion.cvar.map(x => `<td>${usd(x, 0)}</td>`).join("")}</tr><tr><td>SMH drawdown</td>${T.equity.cvar.map(x => `<td>${pc(x)}</td>`).join("")}</tr><tr><td>Sovereign spend</td>${T.sovereign.cvar.map(x => `<td>${usd(x, 0)}</td>`).join("")}</tr></tbody></table></div>
  <h3>Read these first</h3><ul>${run.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
}

let paperLoaded = false;
async function loadPaper() {
  if (paperLoaded) return; paperLoaded = true;
  const status = $("#paper-status");
  try {
    const html = await fetch("/paper-fragment", { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); });
    const root = $("#paper-host").attachShadow({ mode: "open" }); root.innerHTML = html; status.remove();
    // links inside the shadow root: same-page anchors scroll within it; the Contents list jumps to sections
    root.addEventListener("click", e => { const a = e.target.closest('a[href^="#"]'); if (!a) return; const t = root.getElementById(decodeURIComponent(a.getAttribute("href").slice(1))); if (t) { e.preventDefault(); t.scrollIntoView({ behavior: "smooth", block: "start" }); } });
    if (location.hash.length > 1 && !["#deep-dive", "#paper"].includes(location.hash)) { const t = root.getElementById(location.hash.slice(1)); if (t) setTimeout(() => t.scrollIntoView(), 50); }
  } catch (e) { status.innerHTML = `The paper could not be loaded here (${esc(e.message)}). <a href="/paper">Open it as a standalone page.</a>`; paperLoaded = false; }
}

function setupDeep(run) {
  const btn = $("#deep-toggle"), box = $("#deep-dive"); let ready = false;
  const open = (tab) => {
    box.hidden = false; btn.setAttribute("aria-expanded", "true");
    if (!ready) { ready = true; renderMC(run); renderMethod(run); }
    if (tab) pick(tab);
  };
  btn.onclick = () => { if (box.hidden) { open(); } else { box.hidden = true; btn.setAttribute("aria-expanded", "false"); } };
  const tabs = [...document.querySelectorAll(".deeptabs [role=tab]")];
  const pick = t => { tabs.forEach(x => { const on = x === t; x.setAttribute("aria-selected", on); x.tabIndex = on ? 0 : -1; $("#" + x.getAttribute("aria-controls")).hidden = !on; }); if (t.id === "t-paper") loadPaper(); };
  tabs.forEach(t => t.onclick = () => pick(t));
  $(".deeptabs").addEventListener("keydown", e => { const i = tabs.findIndex(x => x.getAttribute("aria-selected") === "true"); const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null; if (n == null) return; const t = tabs[(n + tabs.length) % tabs.length]; pick(t); t.focus(); });
  document.querySelectorAll("[data-open-deep]").forEach(a => a.addEventListener("click", () => { open($("#t-paper")); setTimeout(() => box.scrollIntoView({ block: "start" }), 30); }));
  if (location.hash === "#deep-dive" || location.hash === "#paper") { open(location.hash === "#paper" ? $("#t-paper") : null); setTimeout(() => box.scrollIntoView(), 80); }
}

// ---------------------------------------------------------------------------------------------------------------
(async function main() {
  try {
    const { run, hist } = await load();
    const when = new Date(run.generated_at);
    $("#stamp").textContent = `${run.mode === "live" ? "live data" : "paper inputs, offline"} · run ${when.toLocaleDateString("en", { dateStyle: "medium" })}`;
    renderKpis(run); renderRatings(run); renderHero(run); renderTargets(run); renderHistory(hist); renderInputs(run); setupDeep(run);
  } catch (e) {
    $("#stamp").textContent = "no data";
    $("#lede").innerHTML = `The latest simulation results could not be loaded (${esc(e.message)}). The nightly pipeline writes them to <code>public/data/latest_run.json</code>; until it has run, the paper is still available as a <a href="/paper">standalone page</a>.`;
  }
})();
