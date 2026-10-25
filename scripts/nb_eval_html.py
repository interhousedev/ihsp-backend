"""Standalone HTML snapshots of generated slide decks (for `nb_eval_slides.py`).

The page mirrors the web viewer (`iht-web packages/features-core/src/notebooks/viewers/
slides/`): 16:9 slides sized in container units, the eight layouts, a footer with the
deck title and the slide number, light and dark themes (system setting or the toggle),
a fit-to-slide pass that shrinks dense slides, and a print stylesheet with one slide
per page. Under every slide the review panel shows its sources (title, page, snippet),
the speaker notes and the picture idea, so a reviewer can check the text against the
sources. No external resources: the file opens offline.
"""

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

CSS = """
:root{color-scheme:light dark;--bg:#f4f5f8;--panel:#fff;--ink:#1c1f26;--muted:#5b6270;
--line:#e3e6ec;--s-bg:#fff;--s-fg:#1c1f26;--s-muted:#5b6270;--s-accent:#2f5bd3;
--s-accent-fg:#fff;--s-soft:#f2f5fb;--s-line:#dfe4ee}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111318;
--panel:#1b1e24;--ink:#eef0f4;--muted:#a3aab8;--line:#2c313b;--s-bg:#1b1e24;
--s-fg:#eef0f4;--s-muted:#a3aab8;--s-accent:#7aa2ff;--s-accent-fg:#0d1220;
--s-soft:#232833;--s-line:#343a46}}
:root[data-theme=dark]{--bg:#111318;--panel:#1b1e24;--ink:#eef0f4;--muted:#a3aab8;
--line:#2c313b;--s-bg:#1b1e24;--s-fg:#eef0f4;--s-muted:#a3aab8;--s-accent:#7aa2ff;
--s-accent-fg:#0d1220;--s-soft:#232833;--s-line:#343a46}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header.page{max-width:1100px;margin:0 auto;padding:24px 16px 8px;display:flex;gap:12px;
flex-wrap:wrap;align-items:baseline;justify-content:space-between}
header.page h1{margin:0;font-size:22px}
header.page p{margin:0;color:var(--muted)}
button.theme{border:1px solid var(--line);background:var(--panel);color:var(--ink);
border-radius:8px;padding:6px 12px;cursor:pointer}
main{max-width:1100px;margin:0 auto;padding:8px 16px 48px;display:flex;
flex-direction:column;gap:28px}
.card{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px}
@media (max-width:860px){.card{grid-template-columns:1fr}}
.review{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:12px 14px;font-size:13px;overflow-wrap:anywhere}
.review h3{margin:0 0 4px;font-size:12px;text-transform:none;color:var(--muted)}
.review p{margin:0 0 10px}.review ol{margin:0 0 10px;padding-left:18px}
.review .warn{color:#c2410c;font-weight:600}
.slide{container-type:inline-size;aspect-ratio:16/9;width:100%;position:relative;
overflow:hidden;border-radius:10px;border:1px solid var(--s-line);
background:var(--s-bg);color:var(--s-fg);box-shadow:0 1px 3px rgba(0,0,0,.06);--fit:1;
print-color-adjust:exact;-webkit-print-color-adjust:exact;hyphens:auto}
.body{position:absolute;inset:0 0 6.2cqw 0;display:flex;flex-direction:column;
gap:calc(2.2cqw*var(--fit));padding:5cqw 6cqw 0;overflow:hidden}
.slide[data-layout=title] .body{inset:0;padding:8cqw;justify-content:center;
background:var(--s-accent);color:var(--s-accent-fg)}
.foot{position:absolute;left:6cqw;right:6cqw;bottom:2cqw;display:flex;gap:2cqw;
justify-content:space-between;font-size:1.7cqw;color:var(--s-muted)}
.foot span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.slide[data-layout=title] .foot{display:none}
h2{margin:0;font-size:calc(4.4cqw*var(--fit));line-height:1.15;font-weight:700;
letter-spacing:-.01em;text-wrap:balance;display:-webkit-box;-webkit-line-clamp:3;
-webkit-box-orient:vertical;overflow:hidden;flex:none}
.rule h2{padding-bottom:1.2cqw;border-bottom:.45cqw solid var(--s-accent)}
.slide[data-layout=title] h2{font-size:calc(6.4cqw*var(--fit));-webkit-line-clamp:4}
.slide[data-layout=section] h2{font-size:calc(5.6cqw*var(--fit))}
.slide[data-layout=summary] h2{color:var(--s-accent)}
.accent{width:10cqw;height:.7cqw;border-radius:1cqw;background:currentColor;opacity:.7}
.sub{font-size:calc(3cqw*var(--fit));opacity:.9;margin:0}
p.text{margin:0;font-size:calc(2.6cqw*var(--fit));line-height:1.4;color:var(--s-muted);
text-wrap:pretty}
ul.pts,ol.pts{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;
gap:calc(1.3cqw*var(--fit));font-size:calc(3cqw*var(--fit));line-height:1.3;min-height:0}
ul.pts li{display:flex;gap:1.6cqw;align-items:baseline}
ul.pts li::before{content:"";flex:none;width:1cqw;height:1cqw;border-radius:50%;
background:var(--s-accent);transform:translateY(-.25cqw)}
.slide[data-layout=summary] ul.pts li::before{content:"✓";width:auto;height:auto;
background:none;color:var(--s-accent);font-weight:800;transform:none}
.slide[data-layout=section]{background:var(--s-soft)}
.slide[data-layout=section] .body{justify-content:center;padding-left:9cqw;
border-left:1.4cqw solid var(--s-accent)}
ol.agenda{counter-reset:item;display:grid;gap:calc(1.6cqw*var(--fit)) 4cqw}
ol.agenda.two{grid-template-columns:1fr 1fr}
ol.agenda li{counter-increment:item;display:flex;gap:2cqw;align-items:center}
ol.agenda li::before{content:counter(item);flex:none;display:grid;place-items:center;
width:calc(4.6cqw*var(--fit));height:calc(4.6cqw*var(--fit));border-radius:50%;
background:var(--s-accent);color:var(--s-accent-fg);font-weight:700;
font-size:calc(2.4cqw*var(--fit))}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:2.4cqw;min-height:0;flex:1}
.col{background:var(--s-soft);border:1px solid var(--s-line);border-radius:1.4cqw;
padding:2.4cqw;display:flex;flex-direction:column;gap:1.4cqw;min-height:0;overflow:hidden}
.col h3{margin:0;color:var(--s-accent);font-size:calc(3.2cqw*var(--fit));
line-height:1.2}
.col ul.pts{font-size:calc(2.6cqw*var(--fit))}
figure{margin:0;display:flex;flex-direction:column;justify-content:center;gap:1.6cqw;
flex:1;min-height:0}
.qmark{font:700 11cqw/0.6 Georgia,serif;color:var(--s-accent)}
blockquote{margin:0;font-size:calc(3.6cqw*var(--fit));line-height:1.35;font-style:italic;
font-weight:500}
figcaption{color:var(--s-muted);font-size:calc(2.4cqw*var(--fit))}
table{border-collapse:collapse;width:100%;table-layout:fixed;
font-size:calc(2.3cqw*var(--fit))}
th,td{border:1px solid var(--s-line);padding:calc(.9cqw*var(--fit)) 1.2cqw;
text-align:start;vertical-align:top;overflow-wrap:anywhere}
th{background:color-mix(in srgb,var(--s-accent) 14%,transparent);font-weight:650}
tr:nth-child(even) td{background:var(--s-soft)}
@media print{@page{size:254mm 142.875mm;margin:0}
:root{--s-bg:#fff;--s-fg:#1c1f26;--s-muted:#5b6270;--s-accent:#2f5bd3;--s-accent-fg:#fff;
--s-soft:#f2f5fb;--s-line:#dfe4ee}
body{background:#fff}header.page,.review{display:none}
main{padding:0;max-width:none;gap:0;display:block}
.card{display:block;break-after:page;break-inside:avoid}
.card:last-child{break-after:auto}
.slide{border:0;border-radius:0;box-shadow:none;width:100vw;max-height:100vh}}
"""

FIT_JS = """
document.querySelectorAll('.slide').forEach(function(slide){
  var body=slide.querySelector('.body');var fit=1;
  while(body.scrollHeight>body.clientHeight+1&&fit>0.55){
    fit=Math.round((fit-0.05)*100)/100;slide.style.setProperty('--fit',fit);}
  if(fit<1){slide.dataset.fit=fit;}
});
document.querySelector('button.theme').addEventListener('click',function(){
  var root=document.documentElement;var dark=root.dataset.theme==='dark'||
  (!root.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);
  root.dataset.theme=dark?'light':'dark';});
"""


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _items(items: Sequence[str], css: str = "pts") -> str:
    if not items:
        return ""
    lis = "".join(f"<li><span>{_e(item)}</span></li>" for item in items)
    return f'<ul class="{css}">{lis}</ul>'


def _text(slide: Mapping[str, Any]) -> str:
    body = slide.get("body")
    return f'<p class="text">{_e(body)}</p>' if body else ""


def _title_layout(slide: Mapping[str, Any], subtitle: str | None) -> str:
    lines = slide.get("bullets") or []
    sub = "" if slide.get("body") or lines else subtitle
    parts = [f"<h2>{_e(slide.get('title'))}</h2>", '<div class="accent"></div>']
    if sub:
        parts.append(f'<p class="sub">{_e(sub)}</p>')
    if slide.get("body"):
        parts.append(f'<p class="sub">{_e(slide.get("body"))}</p>')
    return "".join(parts) + _items(lines)


def _agenda(slide: Mapping[str, Any]) -> str:
    items = slide.get("bullets") or []
    two = " two" if len(items) > 5 else ""
    lis = "".join(f"<li><span>{_e(item)}</span></li>" for item in items)
    head = f"<h2>{_e(slide.get('title'))}</h2>"
    return f'{head}<ol class="pts agenda{two}">{lis}</ol>'


def _columns(slide: Mapping[str, Any]) -> str:
    cols = []
    for side in (slide.get("left"), slide.get("right")):
        side = side or {}
        cols.append(
            f'<section class="col"><h3>{_e(side.get("heading"))}</h3>'
            f'{_items(side.get("bullets") or [])}</section>'
        )
    return f"<h2>{_e(slide.get('title'))}</h2><div class=\"cols\">{''.join(cols)}</div>"


def _quote(slide: Mapping[str, Any]) -> str:
    quote = slide.get("quote") or {}
    title = (
        f"<h2 class='qt'>{_e(slide.get('title'))}</h2>" if slide.get("title") else ""
    )
    who = quote.get("attribution")
    caption = f"<figcaption>— {_e(who)}</figcaption>" if who else ""
    return (
        f'{title}<figure><span class="qmark">“</span>'
        f"<blockquote>{_e(quote.get('text'))}</blockquote>{caption}</figure>"
    )


def _table(slide: Mapping[str, Any]) -> str:
    table = slide.get("table") or {}
    head = "".join(f"<th>{_e(c)}</th>" for c in table.get("columns") or [])
    rows = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>"
        for row in table.get("rows") or []
    )
    return (
        f"<h2>{_e(slide.get('title'))}</h2>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    )


def slide_html(
    slide: Mapping[str, Any], number: int, total: int, deck: Mapping[str, Any]
) -> str:
    """One 16:9 slide."""
    layout = str(slide.get("layout"))
    if layout == "title":
        inner = _title_layout(slide, deck.get("subtitle"))
    elif layout == "agenda":
        inner = _agenda(slide)
    elif layout == "two_columns":
        inner = _columns(slide)
    elif layout == "quote":
        inner = _quote(slide)
    elif layout == "table":
        inner = _table(slide)
    else:
        inner = f"<h2>{_e(slide.get('title'))}</h2>{_text(slide)}"
        inner += _items(slide.get("bullets") or [])
    rule = " rule" if layout in ("bullets", "two_columns", "table", "agenda") else ""
    return (
        f'<div class="slide{rule}" data-layout="{_e(layout)}">'
        f'<div class="body">{inner}</div>'
        f'<div class="foot"><span>{_e(deck.get("title"))}</span>'
        f"<span>{number} / {total}</span></div></div>"
    )


def _review(slide: Mapping[str, Any], refs_index: Mapping[str, Any]) -> str:
    refs = []
    for label in slide.get("refs") or []:
        entry = refs_index.get(label) or {}
        page = f", p. {entry['page']}" if entry.get("page") else ""
        refs.append(
            f"<li><b>{_e(label)}</b> {_e(entry.get('source_title'))}{page}: "
            f"<i>{_e(entry.get('snippet'))}</i></li>"
        )
    sources = f"<ol>{''.join(refs)}</ol>" if refs else '<p class="warn">no refs</p>'
    hint = slide.get("visual_hint")
    return (
        '<aside class="review"><h3>Sources</h3>'
        f"{sources}<h3>Speaker notes</h3><p>{_e(slide.get('notes')) or '—'}</p>"
        + (f"<h3>Picture idea</h3><p>{_e(hint)}</p>" if hint else "")
        + "</aside>"
    )


def deck_html(
    deck: Mapping[str, Any],
    refs_index: Mapping[str, Any],
    *,
    heading: str,
    meta: Mapping[str, Any],
) -> str:
    """The whole page: header with the run facts, then slide + review per slide."""
    slides = list(deck.get("slides") or [])
    cards = "".join(
        f'<article class="card">{slide_html(s, n, len(slides), deck)}'
        f"{_review(s, refs_index)}</article>"
        for n, s in enumerate(slides, start=1)
    )
    facts = " · ".join(f"{_e(k)}: {_e(v)}" for k, v in meta.items())
    data = html.escape(json.dumps(deck, ensure_ascii=False))
    return (
        '<!doctype html><html lang="mul"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(deck.get('title'))}</title><style>{CSS}</style></head><body>"
        f'<header class="page"><div><h1>{_e(heading)}</h1><p>{facts}</p></div>'
        '<button class="theme" type="button">Light / dark</button></header>'
        f'<main>{cards}</main><script type="application/json" id="deck">{data}'
        f"</script><script>{FIT_JS}</script></body></html>"
    )


def index_html(rows: Sequence[Mapping[str, Any]]) -> str:
    """A list of the decks of one run with links to their pages."""
    items = "".join(
        f'<li><a href="{_e(r["href"])}">{_e(r["name"])}</a> — {_e(r["summary"])}</li>'
        for r in rows
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Slide eval</title>'
        f'<style>{CSS}</style></head><body><header class="page"><h1>Slide deck '
        f'eval</h1><button class="theme" type="button">Light / dark</button></header>'
        f"<main><ul>{items}</ul></main><script>{FIT_JS}</script></body></html>"
    )
