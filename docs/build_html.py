"""Convierte docs/*.md a HTML publicable (artefacto) con la identidad de Claudia."""
import re
import sys
from pathlib import Path

import markdown

CSS = """
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;1,500&family=Poppins:wght@400;500;600&display=swap">
<style>
:root{
  --bg:#F7F2EE; --surface:#FFFDFB; --ink:#2A1B10; --ink-2:#6B5A4E; --accent:#3B2611; --accent-soft:#E9DCCF;
  --line:#E3D8CF; --good:#2E7D4F; --warn:#B7791F; --crit:#B3402F; --mark:#F3E4D3;
  color-scheme:light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#1E1613; --surface:#271D18; --ink:#F1E9E3; --ink-2:#C9BBAF; --accent:#D9B48F; --accent-soft:#3A2C24;
    --line:#3A2C24; --good:#7BC49A; --warn:#E0B060; --crit:#E58A78; --mark:#3A2C24; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#1E1613; --surface:#271D18; --ink:#F1E9E3; --ink-2:#C9BBAF; --accent:#D9B48F; --accent-soft:#3A2C24;
  --line:#3A2C24; --good:#7BC49A; --warn:#E0B060; --crit:#E58A78; --mark:#3A2C24; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Poppins,"Segoe UI",system-ui,sans-serif;font-size:16px;line-height:1.7;
     padding-block:40px 80px;padding-inline:clamp(16px,5vw,48px)}
.doc{max-width:820px;margin:0 auto}
h1,h2,h3{font-family:"Playfair Display",Georgia,serif;font-weight:600;line-height:1.2;text-wrap:balance;color:var(--ink)}
h1{font-size:clamp(30px,4.5vw,42px);margin:0 0 8px}
h1 + h2{font-family:Poppins,sans-serif;font-weight:500;font-size:15px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2);margin:0 0 24px;border:0;padding:0}
h2{font-size:clamp(22px,3vw,28px);margin:56px 0 16px;padding-top:24px;border-top:1px solid var(--line)}
h3{font-size:19px;margin:36px 0 12px}
p{margin:0 0 16px;max-width:70ch}
ul,ol{max-width:70ch;padding-left:22px}
li{margin-bottom:6px}
strong{font-weight:600}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--mark);padding:1px 6px;border-radius:4px}
hr{border:0;border-top:1px solid var(--line);margin:40px 0}
.meta{color:var(--ink-2);font-size:14px;margin-bottom:8px}
.tbl{overflow-x:auto;margin:20px 0 28px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14.5px;line-height:1.5;font-variant-numeric:tabular-nums}
th,td{padding:11px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{font-weight:600;font-size:12.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2);background:var(--accent-soft)}
tr:last-child td{border-bottom:0}
td:first-child{font-weight:500;white-space:nowrap}
.tbl.compare td:first-child{white-space:normal;min-width:130px}
.tbl.compare th:nth-child(4),.tbl.compare td:nth-child(4){background:var(--mark)}
.tbl.compare td{min-width:200px}
blockquote{margin:24px 0;padding:16px 20px;border-left:3px solid var(--accent);background:var(--surface);font-family:"Playfair Display",serif;font-size:19px;line-height:1.45}
.verdict{margin:16px 0 8px;padding:14px 18px;border-left:3px solid var(--accent);background:var(--surface);max-width:70ch}
.toc{display:flex;flex-wrap:wrap;gap:8px 18px;margin:0 0 40px;padding:0;list-style:none;font-size:14px}
.toc a{color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--line)}
.toc a:hover,.toc a:focus-visible{color:var(--accent);border-color:var(--accent);outline:none}
a{color:var(--accent)}
@media (max-width:600px){ th,td{padding:9px 10px} body{font-size:15px} }
@media (prefers-reduced-motion: reduce){*{scroll-behavior:auto}}
</style>
"""


def build(src: Path, dst: Path, title: str):
    md = src.read_text(encoding="utf-8")
    html = markdown.markdown(md, extensions=["tables", "sane_lists", "toc"], extension_configs={"toc": {"toc_depth": "2"}})
    # Tablas envueltas para scroll horizontal; la comparativa con clase especial
    def wrap(m):
        t = m.group(0)
        cls = "tbl compare" if "Optimizada (B)" in t else "tbl"
        return f'<div class="{cls}">{t}</div>'
    html = re.sub(r"<table>.*?</table>", wrap, html, flags=re.S)
    # "**Veredicto: ...**" → bloque destacado
    html = re.sub(r"<p><strong>Veredicto:(.*?)</strong>(.*?)</p>", r'<div class="verdict"><strong>Veredicto:\1</strong>\2</div>', html, flags=re.S)
    html = html.replace("<p>Fecha:", '<p class="meta">Fecha:').replace("<p>Estado:", '<p class="meta">Estado:')
    # Índice
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', html)
    toc = "".join(f'<li><a href="#{i}">{re.sub("<.*?>", "", t)}</a></li>' for i, t in heads if not t.startswith("Sistema Comercial"))
    html = re.sub(r'(<h1[^>]*>.*?</h1>\s*<h2[^>]*>.*?</h2>\s*<p class="meta">.*?</p>)', r'\1<ul class="toc">' + toc + "</ul>", html, count=1, flags=re.S)
    dst.write_text(CSS.replace("__TITLE__", title) + f'<main class="doc">{html}</main>', encoding="utf-8")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
