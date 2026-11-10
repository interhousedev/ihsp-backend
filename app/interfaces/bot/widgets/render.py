"""OpenUI blocks as self-contained Telegram widget HTML (Bot API 10.4).

A widget is HTML, CSS and JS that run in Telegram's sandbox: no network, no external
scripts, styles, fonts or images, no form controls. The renderer therefore emits
only inline CSS on the theme variables (`--tg-theme-*`), inline SVG and one fixed
script (a click delegate); every string of the block (model output) is escaped as
text or as an attribute value and never reaches the script, a style or a handler.
`audit` re-checks the finished document as a last gate, and a block that is too big
(32768 bytes, 4096 compressed, about 540 px high) or has no widget form returns
None so that the caller falls back to the Markdown rendering.
"""

import math
import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from html import escape as _escape
from urllib.parse import urlsplit

from app.shared.openui.catalog import load_catalog
from app.shared.openui.degrade import block_markdown
from app.shared.openui.lang import Arr, Call, Lit, Node, Obj, Ref, parse_program
from app.shared.openui.validate import validate_block

MAX_HTML_BYTES = 32768
MAX_COMPRESSED_BYTES = 4096  # zlib level 9, as Telegram measures it
MAX_HEIGHT = 540  # the bubble clips at 600 px and never scrolls
MAX_REQUEST_BYTES = 64
MAX_LINK_CHARS = 256
CAPTION_CHARS = 200
TELEGRAM_HOSTS = ("t.me", "telegram.me", "telegram.dog")
SUPPORTED = frozenset(
    {
        "Stack",
        "Card",
        "TextBlock",
        "StatGrid",
        "Table",
        "BarChart",
        "LineChart",
        "Progress",
        "Timetable",
        "LinkList",
        "Flow",
    }
)

Value = str | float | bool | None | list["Value"] | dict[str, "Value"] | Call

# The click delegate: static text, no model data. A button either opens a vetted
# https link or sends a short opaque token (`TelegramWidget.request`, one per tap).
SCRIPT = (
    "<script>document.addEventListener('click',function(e){"
    "var b=e.target.closest('button');"
    "if(!b||!window.TelegramWidget){return;}"
    "var u=b.getAttribute('data-url'),r=b.getAttribute('data-req');"
    "if(u){TelegramWidget.openLink(u);}"
    "else if(r){b.disabled=true;"
    "TelegramWidget.request(r).catch(function(){b.disabled=false;});}"
    "});</script>"
)
META = '<meta charset="utf-8">'
STYLE = (
    "<style>"
    "body{margin:8px 10px;color:var(--tg-theme-text-color);"
    "font:var(--tg-text-font-size,15px)/1.35 system-ui,sans-serif}"
    ".c{background:var(--tg-theme-secondary-bg-color);border-radius:10px;"
    "padding:8px 10px;margin:0 0 6px}"
    ".t{font-weight:600;margin:0 0 4px}"
    ".h{color:var(--tg-theme-hint-color)}"
    ".m{font-size:.9em}"
    ".g{display:grid;grid-template-columns:1fr 1fr;gap:6px}"
    ".s{background:var(--tg-theme-secondary-bg-color);border-radius:8px;"
    "padding:6px 8px}"
    ".v{font-size:1.25em;font-weight:600}"
    "table{border-collapse:collapse;width:100%;font-size:.9em}"
    "th,td{text-align:left;padding:3px 6px;"
    "border-bottom:1px solid var(--tg-theme-section-separator-color)}"
    ".p{height:8px;border-radius:4px;background:var(--tg-theme-secondary-bg-color)}"
    ".p i{display:block;height:100%;border-radius:4px;"
    "background:var(--tg-theme-button-color)}"
    "svg{display:block;width:100%}"
    ".b{fill:var(--tg-theme-button-color)}"
    ".l{fill:none;stroke:var(--tg-theme-button-color);stroke-width:2}"
    ".x{fill:var(--tg-theme-hint-color);font-size:9px}"
    ".f{display:flex;flex-direction:column;align-items:stretch;gap:2px}"
    ".f div{background:var(--tg-theme-secondary-bg-color);border-radius:8px;"
    "padding:4px 8px}"
    ".f .a{background:none;text-align:center;padding:0;"
    "color:var(--tg-theme-hint-color)}"
    "button{display:block;width:100%;margin:4px 0 0;padding:6px 10px;border:0;"
    "border-radius:8px;text-align:left;font:inherit;"
    "background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}"
    "button:disabled{opacity:.6}"
    "</style>"
)

_FORBIDDEN = re.compile(
    r"https?:|//|javascript:|@import|url\(|expression\(|<script|<iframe|<object"
    r"|<embed|<link|<img|<form|<input|<select|<textarea|<meta|<base|\son\w+\s*="
    r"|@font-face|\x00",
    re.IGNORECASE,
)
_ATTRIBUTES = re.compile(r' data-(?:url|req)="[^"]*"')


@dataclass(frozen=True, slots=True)
class Widget:
    """The document to send and the plain caption under it (fallback text)."""

    html: str
    caption: str


class _TooBig(Exception):
    """The block has no widget form, or would not fit the bubble."""


def esc(text: object) -> str:
    """Model text as HTML text or a double-quoted attribute value."""
    return _escape(str(text).replace("\x00", ""), quote=True)


def audit(html: str) -> bool:
    """True when the document has no network, script source or handler markup.

    The fixed script and the vetted `data-url` and `data-req` values are removed
    first; everything else (all of it escaped model text and our own markup) must
    pass the forbidden-construct scan.
    """
    bare = _ATTRIBUTES.sub("", html.replace(SCRIPT, "").replace(META, ""))
    return _FORBIDDEN.search(bare) is None


def fits(html: str) -> bool:
    """The size limits of `sendWidget`: 32768 bytes, 4096 after zlib level 9."""
    data = html.encode("utf-8")
    if len(data) > MAX_HTML_BYTES or b"\x00" in data:
        return False
    return len(zlib.compress(data, 9)) <= MAX_COMPRESSED_BYTES


def _safe_link(url: object) -> str | None:
    """An https URL a widget may open (`openLink`: https, 256 characters, not t.me)."""
    if not isinstance(url, str) or len(url) > MAX_LINK_CHARS:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or any(c.isspace() for c in url):
        return None
    if host in TELEGRAM_HOSTS:
        return None
    return url


def _num(item: Value) -> float:
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise _TooBig
    if not math.isfinite(item):
        raise _TooBig
    return float(item)


def _fmt(item: Value) -> str:
    if isinstance(item, float):
        return f"{item:g}"
    return "" if item is None else str(item)


def _rows(items: Value) -> list[dict[str, Value]]:
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _texts(items: Value) -> list[str]:
    if not isinstance(items, list):
        return []
    return [_fmt(i) for i in items if not isinstance(i, (list, dict, Call))]


class _Page:
    """Renders one parsed block and keeps a running estimate of its height."""

    def __init__(self, value: Callable[[Node], Value]) -> None:
        self.value = value
        self.height = 16.0

    def grow(self, pixels: float) -> None:
        """Count `pixels` of height; a block that cannot fit is not a widget."""
        self.height += pixels
        if self.height > MAX_HEIGHT:
            raise _TooBig

    def title(self, props: dict[str, Value]) -> str:
        text = props.get("title")
        if not text:
            return ""
        self.grow(24)
        return f'<div class="t">{esc(_fmt(text))}</div>'

    def render(self, node: Node) -> str:
        call = self.value(node)
        if not isinstance(call, Call):
            return ""
        spec = load_catalog().component(call.name, "chat")
        if spec is None or call.name not in SUPPORTED:
            raise _TooBig
        props = {
            prop.name: self.value(call.args[i]) if i < len(call.args) else None
            for i, prop in enumerate(spec.props)
        }
        if call.name in ("Stack", "Card"):
            return self._group(call.name, props)
        method = getattr(self, "_" + call.name.lower())
        return method(props)  # type: ignore[no-any-return]

    def _group(self, name: str, props: dict[str, Value]) -> str:
        kids = props["children"]
        items = (
            [k for k in kids if isinstance(k, Call)] if isinstance(kids, list) else []
        )
        inner = "".join(self.render(item) for item in items)
        if name == "Stack":
            return inner
        self.grow(20)
        head = f'<div class="t">{esc(_fmt(props["title"]))}</div>'
        if props.get("subtitle"):
            self.grow(18)
            head += f'<div class="h m">{esc(_fmt(props["subtitle"]))}</div>'
        return f'<div class="c">{head}{inner}</div>'

    def _textblock(self, props: dict[str, Value]) -> str:
        text = _fmt(props["text"])
        self.grow(22 * (1 + len(text) // 40))
        tone = props.get("tone")
        if tone == "heading":
            return f'<div class="t">{esc(text)}</div>'
        css = ' class="h"' if tone == "muted" else ""
        return f"<div{css}>{esc(text)}</div>"

    def _statgrid(self, props: dict[str, Value]) -> str:
        items = _rows(props["items"])
        self.grow(60 * ((len(items) + 1) // 2) + 6)
        cells = "".join(
            '<div class="s">'
            f'<div class="h m">{esc(_fmt(i["label"]))}</div>'
            f'<div class="v">{esc(_fmt(i["value"]))}</div>'
            + (
                f'<div class="h m">{esc(_fmt(i["hint"]))}</div>'
                if i.get("hint")
                else ""
            )
            + "</div>"
            for i in items
        )
        return f'<div class="g">{cells}</div>'

    def _table(self, props: dict[str, Value]) -> str:
        head = _texts(props["columns"])
        body = props["rows"] if isinstance(props["rows"], list) else []
        self.grow(28 * (len(body) + 1))
        caption = ""
        if props.get("caption"):
            self.grow(24)
            caption = f'<div class="t">{esc(_fmt(props["caption"]))}</div>'
        header = "".join(f"<th>{esc(cell)}</th>" for cell in head)
        lines = "".join(
            "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in _texts(row)) + "</tr>"
            for row in body
        )
        return f"{caption}<table><tr>{header}</tr>{lines}</table>"

    def _series(self, props: dict[str, Value]) -> tuple[list[str], list[float]]:
        labels = _texts(props["labels"])
        raw = props["values"]
        numbers = [_num(v) for v in raw] if isinstance(raw, list) else []
        count = min(len(labels), len(numbers))
        if count == 0:
            raise _TooBig
        return labels[:count], numbers[:count]

    def _chart(self, props: dict[str, Value], line: bool) -> str:
        labels, numbers = self._series(props)
        head = self.title(props)
        self.grow(140)
        low, high = min(0.0, *numbers), max(0.0, *numbers)
        span = (high - low) or 1.0

        def y(n: float) -> float:
            return 8 + (high - n) / span * 80

        count, slot = len(numbers), 300 / len(numbers)
        step = max(1, math.ceil(count / 8))
        shapes: list[str] = []
        if line:
            points = " ".join(
                f"{slot * (i + 0.5):.1f},{y(n):.1f}" for i, n in enumerate(numbers)
            )
            shapes.append(f'<polyline class="l" points="{points}"/>')
        else:
            zero = y(0.0)
            for i, n in enumerate(numbers):
                top = min(y(n), zero)
                height = max(1.0, abs(y(n) - zero))
                shapes.append(
                    f'<rect class="b" x="{slot * i + slot * 0.15:.1f}" y="{top:.1f}" '
                    f'width="{slot * 0.7:.1f}" height="{height:.1f}"/>'
                )
        for i in range(0, count, step):
            shapes.append(
                f'<text class="x" text-anchor="middle" x="{slot * (i + 0.5):.1f}" '
                f'y="108">{esc(labels[i][:12])}</text>'
            )
        unit = f" {_fmt(props['unit'])}" if props.get("unit") else ""
        scale = f"{low:g} - {high:g}{unit}"
        self.grow(20)
        return (
            f'{head}<svg viewBox="0 0 300 116" height="116">{"".join(shapes)}</svg>'
            f'<div class="h m">{esc(scale)}</div>'
        )

    def _barchart(self, props: dict[str, Value]) -> str:
        return self._chart(props, line=False)

    def _linechart(self, props: dict[str, Value]) -> str:
        return self._chart(props, line=True)

    def _progress(self, props: dict[str, Value]) -> str:
        value, top = props["value"], props["max"]
        label = esc(_fmt(props["label"]))
        self.grow(44)
        if not isinstance(value, float) or not isinstance(top, float) or top <= 0:
            return f"<div>{label}</div>"
        if not (math.isfinite(value) and math.isfinite(top)):
            raise _TooBig
        percent = max(0.0, min(100.0, value / top * 100))
        return (
            f'<div>{label} <span class="h">{esc(f"{value:g}/{top:g}")}</span></div>'
            f'<div class="p"><i style="width:{percent:.0f}%"></i></div>'
        )

    def _timetable(self, props: dict[str, Value]) -> str:
        entries = _rows(props["entries"])
        head = self.title(props)
        self.grow(32 * len(entries))
        lines = "".join(
            "<tr>"
            f"<td>{esc(_fmt(e['day']))}</td><td>{esc(_fmt(e['time']))}</td>"
            f"<td>{esc(_fmt(e['title']))}"
            + (
                f' <span class="h">{esc(_fmt(e["place"]))}</span>'
                if e.get("place")
                else ""
            )
            + "</td></tr>"
            for e in entries
        )
        return f"{head}<table>{lines}</table>"

    def _linklist(self, props: dict[str, Value]) -> str:
        head = self.title(props)
        parts: list[str] = []
        for link in _rows(props["links"]):
            self.grow(40)
            title = esc(_fmt(link["title"]))
            about = (
                f' <span class="h m">{esc(_fmt(link["description"]))}</span>'
                if link.get("description")
                else ""
            )
            url = _safe_link(link["url"])
            if url is None:
                parts.append(f"<div>{title}{about}</div>")
            else:
                parts.append(f'<button data-url="{esc(url)}">{title}</button>{about}')
        return head + "".join(parts)

    def _flow(self, props: dict[str, Value]) -> str:
        steps = _texts(props["steps"])
        head = self.title(props)
        self.grow(36 * len(steps))
        arrow = '<div class="a">&#8595;</div>'
        return (
            f'{head}<div class="f">'
            + arrow.join(f"<div>{esc(s)}</div>" for s in steps)
            + "</div>"
        )


def _resolver(source: str) -> tuple[Node, Callable[[Node], Value]]:
    program = parse_program(source)

    def value(node: Node) -> Value:
        while isinstance(node, Ref):
            node = program[node.name]
        if isinstance(node, Lit):
            return node.value
        if isinstance(node, Arr):
            return [value(item) for item in node.items]
        if isinstance(node, Obj):
            return {key: value(item) for key, item in node.entries}
        return node

    return program["root"], value


def _caption(source: str) -> str:
    first = block_markdown(source).replace("**", "").strip().splitlines()
    return (first[0] if first else "")[:CAPTION_CHARS]


def render_widget(
    source: str, *, viz_token: str | None = None, visualize_label: str = ""
) -> Widget | None:
    """The widget of one block, or None when it must use the Markdown fallback.

    None: the block is invalid, a component has no widget form, the content would
    not fit the bubble, the document is over the size limits, or the audit finds a
    forbidden construct. `viz_token` adds the "See visualization" request button.
    """
    if validate_block(source):
        return None
    try:
        root, value = _resolver(source)
        page = _Page(value)
        body = page.render(root)
        if viz_token and visualize_label:
            request = f"viz:{viz_token}"
            if len(request.encode()) <= MAX_REQUEST_BYTES:
                page.grow(40)
                body += (
                    f'<button data-req="{esc(request)}">{esc(visualize_label)}</button>'
                )
    except (_TooBig, KeyError, ValueError):
        return None
    html = (
        f'<!doctype html><html><head><meta charset="utf-8">{STYLE}</head>'
        f"<body>{body}{SCRIPT}</body></html>"
    )
    # `<meta` is ours and static; the scan covers the model-fed body and the styles.
    if (
        not body
        or not audit(html.replace('<meta charset="utf-8">', ""))
        or not fits(html)
    ):
        return None
    return Widget(html, _caption(source))
