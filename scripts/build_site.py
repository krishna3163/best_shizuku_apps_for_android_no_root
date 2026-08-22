"""Build a searchable HTML catalog from the README tables."""

from html import escape
from pathlib import Path

from catalog import read

ROOT = Path(__file__).resolve().parents[1]

content, entries = read()
cards = "\n".join(f'<article class="app"><h2><a href="{escape(entry["links"].split("(")[-1].rstrip(")"))}">{escape(entry["name"])}</a></h2><p>{escape(entry["description"])}</p><small>{escape(entry["license"])}</small></article>' for entry in entries)
site = ROOT / "site"
site.mkdir(exist_ok=True)
(site / "index.html").write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Best Shizuku Apps for Android</title><style>:root{{font-family:system-ui,sans-serif;color:#17202a;background:#f4f7f5}}body{{max-width:1180px;margin:auto;padding:32px 20px}}h1{{font-size:clamp(2rem,5vw,4rem);margin:0}}header{{padding:28px 0;border-bottom:1px solid #cbd5d1}}header p{{color:#53635d;max-width:720px}}.controls{{display:flex;gap:12px;margin:24px 0}}input{{padding:12px;flex:1;border:1px solid #aebcb5;border-radius:6px;font:inherit}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}}.app{{background:white;border:1px solid #d5dfda;border-radius:6px;padding:18px}}.app h2{{font-size:1.05rem}}.app a{{color:#176b4d}}.app p{{line-height:1.5;color:#42514a}}small{{color:#65736d}}</style></head><body><header><h1>Best Shizuku Apps for Android</h1><p>Search no-root Android apps, wireless ADB tools, debloat utilities and Shizuku-compatible projects.</p></header><main><div class="controls"><input id="search" placeholder="Search apps and tools"></div><p id="count"></p><section class="grid">{cards}</section></main><script>const input=document.querySelector('#search'),cards=[...document.querySelectorAll('.app')],count=document.querySelector('#count');function filter(){{let q=input.value.toLowerCase(),n=0;cards.forEach(c=>{{let ok=c.textContent.toLowerCase().includes(q);c.hidden=!ok;if(ok)n++}});count.textContent=n+' apps shown'}}input.oninput=filter;filter();</script></body></html>''', encoding="utf-8")
print(f"Built {len(entries)} app cards")