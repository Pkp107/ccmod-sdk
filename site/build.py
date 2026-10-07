"""Build the ccmod documentation site: site/pages/*.md -> site/_out/*.html (static, no JS framework).

    python site/build.py            # build into site/_out
    python site/build.py --serve    # build, then serve on http://127.0.0.1:8700

Each page starts with a small front matter block:
    ---
    title: Page title
    section: Getting started
    order: 10
    ---
"""
from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
PAGES = HERE / "pages"
OUT = HERE / "_out"
SECTIONS = ["Getting started", "Using ccmod", "Building", "Reference", "Project"]


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {"title": path.stem, "section": "Project", "order": "100"}
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        text = text[m.end():]
    return {"slug": path.stem, "body": text, **meta}


def render(md_text: str) -> tuple[str, list[tuple[str, str, int]]]:
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "admonition", "attr_list"],
                           extension_configs={"toc": {"toc_depth": "2-3", "permalink": "#"}})
    body = md.convert(md_text)
    toc = [(t["id"], t["name"], t["level"]) for t in _flat(md.toc_tokens)]
    return body, toc


def _flat(tokens, out=None):
    out = [] if out is None else out
    for t in tokens:
        out.append(t)
        _flat(t.get("children", []), out)
    return out


def nav_html(pages: list[dict], current: str) -> str:
    parts = []
    for sec in SECTIONS:
        items = sorted((p for p in pages if p["section"] == sec), key=lambda p: (int(p["order"]), p["title"]))
        if not items:
            continue
        parts.append(f'<div class="navsec">{html.escape(sec)}</div>')
        for p in items:
            cls = ' class="cur"' if p["slug"] == current else ""
            href = "./" if p["slug"] == "index" else f'{p["slug"]}.html'
            parts.append(f'<a{cls} href="{href}">{html.escape(p["title"])}</a>')
    return "\n".join(parts)


def page_html(p: dict, pages: list[dict]) -> str:
    body, toc = render(p["body"])
    toc_html = "".join(f'<a class="l{lvl}" href="#{i}">{html.escape(n)}</a>' for i, n, lvl in toc if lvl <= 3)
    title = "ccmod" if p["slug"] == "index" else f'{p["title"]} · ccmod'
    return TEMPLATE.format(title=html.escape(title), nav=nav_html(pages, p["slug"]), body=body,
                           toc=f'<div class="tocbox"><div class="tochead">On this page</div>{toc_html}</div>' if len(toc) > 2 else "")


# existing repo docs published as pages too: file -> (slug, title, section, order)
IMPORTED = {
    "AFTER-EFFECTS-GAP.md": ("after-effects", "After Effects gap analysis", "Project", "30"),
    "SDK-VISION.md": ("sdk-vision", "SDK vision & levers", "Project", "40"),
    "CCPACK-SPEC.md": ("ccpack-spec", "Legacy .ccpack transition spec", "Reference", "60"),
    "AUTHORING.md": ("ccpack-authoring", "Legacy transition pack authoring", "Reference", "70"),
}


def imported() -> list[dict]:
    out = []
    for fn, (slug, title, section, order) in IMPORTED.items():
        f = HERE.parent / "docs" / "reference" / fn
        if f.exists():
            out.append({"slug": slug, "title": title, "section": section, "order": order, "body": re.sub(r"(?<![A-Za-z_])CCMOD(?![A-Za-z_])", "ccmod", f.read_text(encoding="utf-8"))})
    return out


def build() -> int:
    pages = [parse(p) for p in sorted(PAGES.glob("*.md"))] + imported()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for p in pages:
        (OUT / ("index.html" if p["slug"] == "index" else f'{p["slug"]}.html')).write_text(page_html(p, pages), encoding="utf-8")
    assets = HERE / "assets"
    if assets.is_dir():
        shutil.copytree(assets, OUT / "assets")
    import json
    idx = []
    for p in pages:
        text = re.sub(r"[`#*|>_\-]+", " ", re.sub(r"```.*?```", " ", p["body"], flags=re.S))
        idx.append({"u": "index.html" if p["slug"] == "index" else p["slug"] + ".html", "t": p["title"], "s": p["section"],
                    "x": re.sub(r"\s+", " ", text)[:6000]})
    (OUT / "search.json").write_text(json.dumps(idx), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"built {len(pages)} pages -> {OUT}")
    return len(pages)


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="icon" href="assets/logo.png">
<style>
:root{{--bg:#fbfbfc;--panel:#f1f2f4;--fg:#1d2024;--mut:#5d6570;--line:#dfe2e6;--acc:#0a8fa0;--code:#eceef1;--codefg:#1d2024}}
@media (prefers-color-scheme:dark){{:root{{--bg:#17181a;--panel:#1f2124;--fg:#e4e6e9;--mut:#9aa1aa;--line:#2f3236;--acc:#7fd6e8;--code:#101113;--codefg:#dfe3e8}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
header{{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 20px;display:flex;align-items:center;gap:14px}}
img{{max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px}}header img.logo{{width:28px;height:28px;border:0;border-radius:50%}}header b{{font-size:18px;letter-spacing:.5px}} header span{{color:var(--mut);font-size:14px}}
header a{{margin-left:auto;color:var(--acc);text-decoration:none;font-size:14px}}
.wrap{{display:grid;grid-template-columns:240px minmax(0,1fr) 210px;max-width:1280px;margin:0 auto;gap:0}}
nav{{padding:20px 16px;border-right:1px solid var(--line);position:sticky;top:50px;align-self:start;max-height:calc(100vh - 50px);overflow:auto}}
nav a{{display:block;padding:4px 10px;border-radius:6px;color:var(--fg);text-decoration:none;font-size:14.5px}}
nav a:hover{{background:var(--panel)}} nav a.cur{{background:var(--panel);color:var(--acc);font-weight:600}}
.navsec{{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:18px 10px 4px}}
main{{padding:28px 40px 80px;min-width:0}}
aside{{padding:28px 16px;position:sticky;top:50px;align-self:start;font-size:13px}}
.tochead{{color:var(--mut);text-transform:uppercase;font-size:11.5px;letter-spacing:.08em;margin-bottom:6px}}
aside a{{display:block;color:var(--mut);text-decoration:none;padding:2px 0}} aside a:hover{{color:var(--acc)}} aside a.l3{{padding-left:12px}}
h1{{font-size:2rem;margin:.2em 0 .5em}} h2{{margin-top:2em;padding-top:.4em;border-top:1px solid var(--line)}} h3{{margin-top:1.6em}}
a{{color:var(--acc)}} .headerlink{{opacity:0;margin-left:.3em;text-decoration:none}} h2:hover .headerlink,h3:hover .headerlink{{opacity:.6}}
code{{background:var(--code);color:var(--codefg);padding:.12em .35em;border-radius:4px;font:13.5px ui-monospace,Consolas,monospace}}
pre{{background:var(--code);color:var(--codefg);padding:14px 16px;border-radius:8px;overflow:auto;line-height:1.5}} pre code{{background:none;padding:0}}
table{{border-collapse:collapse;width:100%;display:block;overflow:auto;margin:1em 0}} th,td{{border:1px solid var(--line);padding:6px 11px;text-align:left;vertical-align:top}} th{{background:var(--panel)}}
blockquote{{margin:1em 0;padding:.2em 1em;border-left:3px solid var(--acc);background:var(--panel);color:var(--mut)}}
.admonition{{margin:1.2em 0;padding:.6em 1em;border-left:4px solid var(--acc);background:var(--panel);border-radius:0 8px 8px 0}}
.admonition.warning{{border-color:#d9822b}} .admonition.danger{{border-color:#d9444e}} .admonition-title{{font-weight:700;margin:0 0 .2em}}
@media (max-width:1000px){{.wrap{{grid-template-columns:200px minmax(0,1fr)}} aside{{display:none}}}}
@media (max-width:700px){{.wrap{{grid-template-columns:1fr}} nav{{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line)}} main{{padding:20px 16px 60px}}}}
header input{{margin-left:16px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--fg);width:220px}}
#res{{position:absolute;top:46px;left:120px;width:min(520px,90vw);background:var(--bg);border:1px solid var(--line);border-radius:8px;display:none;max-height:70vh;overflow:auto;box-shadow:0 8px 30px #0006}}
#res a{{display:block;margin:0;padding:8px 12px;color:var(--fg);text-decoration:none;border-bottom:1px solid var(--line);font-size:14px}}#res a small{{display:block;color:var(--mut)}}#res a:hover{{background:var(--panel)}}
</style></head><body>
<header><img src="assets/logo.png" alt="" class="logo"><b>ccmod</b><span>build your own CapCut</span><input id="q" type="search" placeholder="Search docs" autocomplete="off"><div id="res"></div><a href="https://github.com/Pkp107/capcut-ccmod">GitHub</a></header>
<div class="wrap"><nav>{nav}</nav><main>{body}</main><aside>{toc}</aside></div>
<script>
(function(){{var q=document.getElementById("q"),r=document.getElementById("res"),d=null;
function load(c){{if(d)return c();fetch("search.json").then(function(x){{return x.json()}}).then(function(j){{d=j;c()}})}}
q.addEventListener("input",function(){{var t=q.value.trim().toLowerCase();if(!t){{r.style.display="none";return}}
load(function(){{var w=t.split(/[ ]+/),h=[];d.forEach(function(p){{var hay=(p.t+" "+p.x).toLowerCase(),sc=0;
for(var i=0;i<w.length;i++){{var k=hay.indexOf(w[i]);if(k<0){{sc=-1;break}}sc+=p.t.toLowerCase().indexOf(w[i])>=0?10:1}}
if(sc>0){{var k2=hay.indexOf(w[0]),a=Math.max(0,k2-40);h.push([sc,p,(p.x.substr(a,110))])}}}});
h.sort(function(a,b){{return b[0]-a[0]}});
r.innerHTML=h.slice(0,8).map(function(e){{return '<a href="'+e[1].u+'">'+e[1].t+'<small>'+e[1].s+' &middot; '+e[2].replace(/</g,"&lt;")+'</small></a>'}}).join("")||'<a>No results</a>';r.style.display="block"}})}});
document.addEventListener("click",function(e){{if(e.target!==q&&!r.contains(e.target))r.style.display="none"}})}})();
</script></body></html>
"""

if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        import functools
        import http.server
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        http.server.ThreadingHTTPServer(("127.0.0.1", 8700), h).serve_forever()
