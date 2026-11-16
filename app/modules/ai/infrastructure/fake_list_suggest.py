"""Deterministic fake document for the admission list suggestion.

It reads the `[candidate:N]` lines of the request so the proposals point at real
catalog rows when the app runs without a key.
"""

import re
from collections.abc import Sequence
from typing import Any

LIST_SUGGEST_SCHEMA = "list_suggest"

_CANDIDATE = re.compile(r"^\[candidate:(\d+)\]", re.MULTILINE)
_LABELS = ("safety", "target", "reach")


def build_list_suggest_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a schema-valid list suggestion document, else None."""
    if schema_name != LIST_SUGGEST_SCHEMA:
        return None
    text = "\n".join(str(m.get("content", "")) for m in messages)
    numbers = list(dict.fromkeys(int(n) for n in _CANDIDATE.findall(text)))[:3]
    return {
        "suggestions": [
            {
                "candidate": n,
                "label": _LABELS[rank % len(_LABELS)],
                "reason": "Adds balance to your list.",
            }
            for rank, n in enumerate(numbers)
        ]
    }
