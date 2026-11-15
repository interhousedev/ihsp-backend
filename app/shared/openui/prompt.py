"""The system prompt section that teaches an assistant when and how to use OpenUI."""

from app.shared.openui.catalog import Subset, load_catalog
from app.shared.openui.finalize import catalog_lines

_CHAT = """
## Visual blocks
Answer in text by default; prose questions stay plain text. A requested table,
comparison, chart, diagram, statistics or visual is always a block, never a Markdown
table (fetch the data first). A block also fits a timetable, a list of links or a
step-by-step plan. At most {max_blocks} blocks, each after one short sentence. Never
say you cannot draw: blocks are how you draw.

Syntax: a ```{fence} code fence, one `name = Expression` per line, entry
`root = {root}([...])`. Arguments are POSITIONAL in the listed order (`?` optional, null
skips): Card("Title", [x]), never Card(title: "Title"). Values: "strings", numbers,
true/false/null, [arrays], {{key: value}} objects, statement names. No $state,
@functions, HTML or images; links are https only.

Examples of an answer:
Here is the comparison:
```{fence}
root = Stack([t])
t = Table(["", "Mitosis", "Meiosis"], [["Cells", 2, 4], ["Divisions", 1, 2]])
```
Your average is rising:
```{fence}
root = Stack([c])
c = LineChart(["Week 1", "Week 2"], [4.2, 4.6], "Average mark")
```

Components:
{catalog}
"""

_STUDIO = """
A question or explanation may include one small visual block (a chart, a table or a
diagram) only when the item is about data. Format: Markdown code fenced with
`{fence}`, OpenUI Lang, `root = ...`, positional arguments, components:
{catalog}
"""


def openui_prompt(subset: Subset = "chat") -> str:
    """The instructions and the component catalog of a subset."""
    catalog = load_catalog()
    template = _CHAT if subset == "chat" else _STUDIO
    return template.format(
        fence=catalog.fence,
        root=catalog.root,
        max_blocks=catalog.limits["max_blocks"],
        catalog=catalog_lines(subset, compact=subset == "chat"),
    )


_TELEGRAM = """
## Visual blocks
Answer in text by default. A requested table, comparison, chart, diagram, statistics,
timetable or list of links is a visual block: call the tool `show_ui_block` with the
block code (fetch the data first). The bot shows the blocks at the end of the answer
message, after your text, so never put a block or a code fence of one in the answer
text; add one short sentence about it. At most {max_blocks} calls per answer. If the
tool lists errors, fix the block and call it again. Never say you cannot draw.

Syntax of `block`: one `name = Expression` per line, entry
`root = {root}([...])`. Arguments are POSITIONAL in the listed order (`?` optional, null
skips): Card("Title", [x]), never Card(title: "Title"). Values: "strings", numbers,
true/false/null, [arrays], {{key: value}} objects, statement names. No $state,
@functions, HTML or images; links are https only.

Example block:
root = Stack([t])
t = Table(["", "Mitosis", "Meiosis"], [["Cells", 2, 4], ["Divisions", 1, 2]])

Components:
{catalog}
"""


def telegram_openui_prompt() -> str:
    """The tool-based block instructions of the Telegram bot (no fences in text)."""
    catalog = load_catalog()
    return _TELEGRAM.format(
        root=catalog.root,
        max_blocks=catalog.limits["max_blocks"],
        catalog=catalog_lines("chat", compact=True),
    )
