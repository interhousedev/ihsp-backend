"""OpenUI blocks as plain Markdown, for surfaces that cannot render them (Telegram).

A valid block becomes headings, `label: value` lines, small text bar charts and
Markdown links; an invalid or unfinished block is left out (the text stays).
"""

from collections.abc import Callable

from app.shared.openui.blocks import split_blocks
from app.shared.openui.catalog import load_catalog
from app.shared.openui.lang import Arr, Call, Lit, Node, Obj, Ref, parse_program
from app.shared.openui.validate import validate_block

BAR_WIDTH = 10
Value = str | float | bool | None | list["Value"] | dict[str, "Value"] | Call


def degrade_to_markdown(text: str) -> str:
    """The answer with every block turned into Markdown (or removed)."""
    out: list[str] = []
    for part in split_blocks(text):
        if part.kind == "text":
            out.append(part.text)
        elif part.kind == "block" and not validate_block(part.text):
            out.append(block_markdown(part.text) + "\n")
    return "".join(out)


def block_markdown(source: str) -> str:
    """One valid block as Markdown."""
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

    return _render(program["root"], value).strip()


def _render(node: Node, value: Callable[[Node], Value]) -> str:
    call = value(node)
    if not isinstance(call, Call):
        return ""
    spec = load_catalog().component(call.name, "chat")
    if spec is None:
        return ""
    props = {
        prop.name: value(call.args[i]) if i < len(call.args) else None
        for i, prop in enumerate(spec.props)
    }
    if call.name in ("Stack", "Card"):
        kids = props["children"]
        items = (
            [k for k in kids if isinstance(k, Call)] if isinstance(kids, list) else []
        )
        body = "\n\n".join(_render(item, value) for item in items)
        head = f"**{props['title']}**\n" if call.name == "Card" else ""
        return head + body
    render = _RENDERERS.get(call.name)
    return render(props) if render else ""


def _fmt(item: Value) -> str:
    if isinstance(item, float):
        return f"{item:g}"
    return "" if item is None else str(item)


def _title(props: dict[str, Value]) -> str:
    return f"**{props['title']}**\n" if props.get("title") else ""


def _rows(items: Value) -> list[dict[str, Value]]:
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _texts(items: Value) -> list[str]:
    return [_fmt(i) for i in items] if isinstance(items, list) else []


def _text(props: dict[str, Value]) -> str:
    text = _fmt(props["text"])
    return f"**{text}**" if props.get("tone") == "heading" else text


def _stats(props: dict[str, Value]) -> str:
    return "\n".join(
        f"• {_fmt(i['label'])}: **{_fmt(i['value'])}**"
        + (f" ({_fmt(i['hint'])})" if i.get("hint") else "")
        for i in _rows(props["items"])
    )


def _table(props: dict[str, Value]) -> str:
    head = " | ".join(_texts(props["columns"]))
    rows = props["rows"] if isinstance(props["rows"], list) else []
    lines = [" | ".join(_texts(row)) for row in rows]
    caption = f"**{props['caption']}**\n" if props.get("caption") else ""
    return caption + "\n".join([f"**{head}**", *lines])


def _chart(props: dict[str, Value]) -> str:
    labels, values = _texts(props["labels"]), props["values"]
    numbers = (
        [v for v in values if isinstance(v, float)] if isinstance(values, list) else []
    )
    top = max((abs(v) for v in numbers), default=0.0) or 1.0
    unit = f" {props['unit']}" if props.get("unit") else ""
    lines = [
        f"{label}: {'▇' * max(1, round(abs(n) / top * BAR_WIDTH))} {n:g}{unit}"
        for label, n in zip(labels, numbers)
    ]
    return _title(props) + "\n".join(lines)


def _progress(props: dict[str, Value]) -> str:
    value, top = props["value"], props["max"]
    if not isinstance(value, float) or not isinstance(top, float) or top <= 0:
        return _fmt(props["label"])
    filled = max(0, min(BAR_WIDTH, round(value / top * BAR_WIDTH)))
    bar = "▇" * filled + "░" * (BAR_WIDTH - filled)
    return f"{_fmt(props['label'])}: {bar} {value:g}/{top:g}"


def _timetable(props: dict[str, Value]) -> str:
    return _title(props) + "\n".join(
        f"• {_fmt(e['day'])} {_fmt(e['time'])} - {_fmt(e['title'])}"
        + (f" ({_fmt(e['place'])})" if e.get("place") else "")
        for e in _rows(props["entries"])
    )


def _links(props: dict[str, Value]) -> str:
    return _title(props) + "\n".join(
        f"• [{_fmt(link['title'])}]({_fmt(link['url'])})"
        + (f" - {_fmt(link['description'])}" if link.get("description") else "")
        for link in _rows(props["links"])
    )


def _flow(props: dict[str, Value]) -> str:
    return _title(props) + " → ".join(_texts(props["steps"]))


_RENDERERS: dict[str, Callable[[dict[str, Value]], str]] = {
    "TextBlock": _text,
    "StatGrid": _stats,
    "Table": _table,
    "BarChart": _chart,
    "LineChart": _chart,
    "Progress": _progress,
    "Timetable": _timetable,
    "LinkList": _links,
    "Flow": _flow,
}
