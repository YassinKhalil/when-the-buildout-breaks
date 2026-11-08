"""Render this repository as a static website: README and docs as HTML (formulas typeset with KaTeX, diagrams with Mermaid),
a source viewer, raw files and a zip download.

    python deploy/build_open_site.py OUT_DIR [BASE_URL_PATH]      # default base path: /open-source

Needs the `markdown` package. Run from the repository root.
"""
import html
import os
import re
import shutil
import subprocess
import sys

import markdown

ROOT = os.getcwd()
OUT = os.path.abspath(sys.argv[1])
BASE = (sys.argv[2] if len(sys.argv) > 2 else "/open-source").rstrip("/")

CSS = """
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#6b645f;--line:#e7e5e4;--acc:#b45309;--soft:#f5f5f4;--link:#9a3412}
@media (prefers-color-scheme:dark){:root{--bg:#141210;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;--line:#2e2a27;--acc:#f59e0b;--soft:#24201d;--link:#fdba74}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.62 Georgia,'Iowan Old Style',serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);font:14px system-ui,sans-serif}
header .in{max-width:900px;margin:0 auto;padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header a{color:var(--mute);text-decoration:none}header a:hover{color:var(--ink)}header b{color:var(--ink)}header .sp{flex:1}
main{max-width:900px;margin:0 auto;padding:10px 16px 70px}
h1{font-size:34px;line-height:1.15;margin:28px 0 8px;letter-spacing:-.015em}h2{font-size:25px;margin:40px 0 8px;border-top:1px solid var(--line);padding-top:22px}h3{font-size:19px;margin:26px 0 4px}
a{color:var(--link)}p{margin:10px 0}li{margin:5px 0}
code{font:13.5px ui-monospace,Menlo,monospace;background:var(--soft);padding:1px 5px;border-radius:4px}
pre{background:var(--soft);padding:12px 14px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5}pre code{background:none;padding:0}
pre.src{font-size:12.5px;line-height:1.45}
table{border-collapse:collapse;width:100%;font:14px/1.4 system-ui,sans-serif;margin:12px 0;display:block;overflow-x:auto}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--mute);border-bottom:2px solid var(--line)}
blockquote{margin:14px 0;padding:6px 16px;border-left:3px solid var(--acc);color:var(--mute);background:var(--card)}
.katex-display{overflow-x:auto;overflow-y:hidden;padding:4px 0}
.btn{display:inline-block;padding:8px 14px;border:1px solid var(--line);border-radius:8px;background:var(--card);text-decoration:none;font:15px system-ui,sans-serif;margin:4px 6px 4px 0}
.mute{color:var(--mute);font:14px system-ui,sans-serif}
pre.mermaid{background:var(--card);text-align:center}
"""
HEAD_EXTRA = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>window.addEventListener('load',()=>{if(window.renderMathInElement)renderMathInElement(document.body,{delimiters:[{left:'\\\\[',right:'\\\\]',display:true},{left:'\\\\(',right:'\\\\)',display:false}],throwOnError:false});
if(window.mermaid){mermaid.initialize({startOnLoad:false,theme:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'default'});mermaid.run({querySelector:'pre.mermaid'});}});</script>"""

esc = html.escape


def page(title, body, depth=0):
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>{HEAD_EXTRA}<style>{CSS}</style></head><body>
<header><div class="in"><b>When the Buildout Breaks</b><a href="/paper">Paper</a><a href="/">Dashboard</a><a href="{up}index.html">Open source</a><a href="{up}docs/01-overview.html">Docs</a><a href="{up}src/index.html">Source</a><span class="sp"></span><a href="https://github.com/YassinKhalil/when-the-buildout-breaks">GitHub</a><a href="{BASE}/ai-bust-open.zip">Download .zip</a></div></header>
<main>{body}</main></body></html>"""


def render_md(text, depth=0):
    code = []

    def hide_code(m):
        code.append(m.group(0))
        return f"XCODE{len(code) - 1}X"
    t = re.sub(r"```.*?```", hide_code, text, flags=re.S)
    t = re.sub(r"`[^`\n]+`", hide_code, t)
    t = t.replace("\\$", "XDOLLARX")
    maths = []

    def hide_math(m, display):
        maths.append((display, m.group(1)))
        return f"XMATH{len(maths) - 1}X"
    t = re.sub(r"\$\$(.+?)\$\$", lambda m: hide_math(m, True), t, flags=re.S)
    t = re.sub(r"(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$", lambda m: hide_math(m, False), t)
    t = re.sub(r"XCODE(\d+)X", lambda m: code[int(m.group(1))], t)
    h = markdown.markdown(t, extensions=["tables", "fenced_code", "sane_lists"])
    h = re.sub(r"XMATH(\d+)X", lambda m: (f'<div class="math">\\[{esc(maths[int(m.group(1))][1].strip())}\\]</div>' if maths[int(m.group(1))][0]
                                          else f'\\({esc(maths[int(m.group(1))][1].strip())}\\)'), h)
    h = h.replace("XDOLLARX", "$")
    h = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', h, flags=re.S)
    # relative links between repository files -> site pages
    def fix(m):
        url = m.group(1)
        if url.startswith(("http", "#", "mailto:", "/")):
            return m.group(0)
        path, _, frag = url.partition("#")
        up = "../" * depth
        if path == "docs/paper.md":
            return f'href="/paper{"#" + frag if frag else ""}"'
        if path.endswith(".md") and path.startswith("docs/"):
            new = f"{up}{path[:-3]}.html"
        elif path.startswith("../") and path.endswith(".md"):
            new = f"{up}{path[3:-3]}.html"
        elif re.match(r"^[\w-]+\.md$", path) and depth == 1:
            new = f"{up}{path[:-3].lower()}.html" if path != "paper.md" else f"{up}docs/paper.html"
        elif re.match(r"^(\d\d-[\w-]+)\.md$", path) and depth == 1:
            new = path[:-3] + ".html"
        elif path in ("CONTRIBUTING.md",):
            new = f"{up}contributing.html"
        elif path.startswith("../"):
            new = f"{up}raw/{path[3:]}"
        else:
            new = f"{up}raw/{path}"
        return f'href="{new}{"#" + frag if frag else ""}"'
    return re.sub(r'href="([^"]+)"', fix, h)


def write(path, content):
    path = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    # raw copies
    for f in files:
        os.makedirs(os.path.dirname(os.path.join(OUT, "raw", f)) or os.path.join(OUT, "raw"), exist_ok=True)
        shutil.copy(f, os.path.join(OUT, "raw", f))
    # docs pages
    for f in sorted(files):
        if f.startswith("docs/") and f.endswith(".md"):
            body = render_md(open(f, encoding="utf-8").read(), depth=1)
            write(f[:-3] + ".html", page(os.path.basename(f), body, 1))
    write("contributing.html", page("Contributing", render_md(open("CONTRIBUTING.md").read(), 0), 0))
    # source viewer
    src_files = [f for f in sorted(files) if f.endswith((".py", ".sh", ".yml", ".example", ".cff", ".txt")) or f in ("NOTICE", "LICENSE", ".gitignore")]
    rows = []
    for f in src_files:
        text = open(f, encoding="utf-8", errors="replace").read()
        name = f.replace("/", "__")
        write(f"src/{name}.html", page(f, f'<h1>{esc(f)}</h1><p class="mute"><a href="../raw/{esc(f)}">raw file</a> · {len(text.splitlines()):,} lines</p><pre class="src"><code>{esc(text)}</code></pre>', 1))
        rows.append(f'<tr><td><a href="{esc(name)}.html">{esc(f)}</a></td><td>{len(text.splitlines()):,}</td><td><a href="../raw/{esc(f)}">raw</a></td></tr>')
    data = [f for f in sorted(files) if f.endswith(".json") or f.endswith(".md") or f.startswith("LICENSE")]
    drows = [f'<tr><td>{esc(f)}</td><td></td><td><a href="../raw/{esc(f)}">raw</a></td></tr>' for f in data]
    write("src/index.html", page("Source", "<h1>Source and data files</h1><p class=\"mute\">Code is Apache-2.0; paper, docs and results are CC BY 4.0. Keep the NOTICE if you redistribute.</p>"
                                 "<h2>Code</h2><table><tr><th>File</th><th>Lines</th><th></th></tr>" + "".join(rows) + "</table>"
                                 "<h2>Results, text and licenses</h2><table><tr><th>File</th><th></th><th></th></tr>" + "".join(drows) + "</table>", 1))
    # zip
    zbase = os.path.join(OUT, "ai-bust-open")
    subprocess.run(["git", "archive", "--format=zip", "--prefix=ai-bust-open/", "-o", zbase + ".zip", "HEAD"], check=True)
    # index = README + links
    readme = render_md(open("README.md", encoding="utf-8").read(), 0)
    top = ('<p><a class="btn" href="docs/01-overview.html">Read the docs</a><a class="btn" href="/paper">The paper</a>'
           f'<a class="btn" href="src/index.html">Browse the source</a><a class="btn" href="{BASE}/ai-bust-open.zip">Download .zip</a></p>')
    write("index.html", page("When the Buildout Breaks: open source", top + readme, 0))
    print("built", OUT, len(files), "files")


main()
