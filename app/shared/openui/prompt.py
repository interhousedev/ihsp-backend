"""The system prompt section that teaches an assistant when and how to use OpenUI."""

from app.shared.openui.catalog import Subset, load_catalog
from app.shared.openui.finalize import catalog_lines

_CHAT = """
## Visual blocks (OpenUI)
Answer in text by default. Add a visual block only when it clearly helps more than
text: a statistics summary, a progress chart, a comparison table, a timetable or a
list of links. At most {max_blocks} blocks per answer, each after a sentence that
introduces it. Never put the whole answer into a block.

A block is fenced Markdown code with the language `{fence}` written in OpenUI Lang:
one statement per line `name = Expression`, the entry is `root = {root}([...])`,
components take POSITIONAL arguments in the order listed below (`?` = optional,
use null to skip one). Values: "strings", numbers, true/false/null, [arrays],
{{key: value}} objects and names of other statements. Nothing else: no $state, no
@functions, no HTML, links only as https URLs, no images.

Example:
```{fence}
root = Stack([stats, chart])
stats = StatGrid([{{label: "Average", value: 4.6}}, {{label: "Absences", value: 2}}])
chart = LineChart(["Week 1", "Week 2", "Week 3"], [4.2, 4.5, 4.6], "Average mark")
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
        catalog=catalog_lines(subset),
    )
