"""Routes for the unified static front end (public/): overview page, /ui assets, /data files and the paper as an embeddable fragment.

ai_bust_live.py calls ``register(app, HERE)`` at start-up; everything here is read-only GET.
The paper fragment is derived from paper.html (built by build_site.py) on first request and cached by file mtime, so
build_site.py stays the single source of the paper.
"""
from __future__ import annotations

import os
import re

_CACHE: dict = {}


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

    if os.path.isdir(os.path.join(pub, "ui")):
        app.mount("/ui", NoCache(directory=os.path.join(pub, "ui")), name="ui")
    if os.path.isdir(os.path.join(pub, "data")):
        app.mount("/data", NoCache(directory=os.path.join(pub, "data")), name="data")

    @app.get("/paper-fragment", response_class=HTMLResponse)
    def fragment():
        path = os.path.join(here, "paper.html")
        if not os.path.exists(path):
            raise HTTPException(404, "paper.html not built; run build_site.py")
        m = os.path.getmtime(path)
        if _CACHE.get("m") != m:
            _CACHE.update(m=m, html=paper_fragment(open(path, encoding="utf-8").read()))
        return HTMLResponse(_CACHE["html"], headers={"Cache-Control": "no-cache"})

    @app.get("/dashboard", response_class=HTMLResponse)
    def legacy_dashboard():
        with open(os.path.join(here, "dashboard.html"), encoding="utf-8") as f:       # the original live-feed dashboard, kept
            return f.read()


def index_html(here: str) -> str | None:
    p = os.path.join(here, "public", "index.html")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None
