"""Deterministic fake advice for a student's university, used without a key."""

import re
from collections.abc import Sequence
from typing import Any

SCHEMA = "uni_advice"

_NAME = re.compile(r"^University: ([^\n(]+)", re.MULTILINE)


def build_uni_advice_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a schema-valid advice document, else None."""
    if schema_name != SCHEMA:
        return None
    text = "\n".join(str(m.get("content", "")) for m in messages)
    found = _NAME.search(text)
    name = found.group(1).strip() if found else "this university"
    return {
        "questions": [
            f"What does {name} look for in applicants like me?",
            f"Which deadlines and rounds at {name} fit my plan?",
        ],
        "academic": [
            {
                "title": "Strengthen your core subjects",
                "detail": f"Check the course and score expectations of {name}.",
            }
        ],
        "activities": [
            {
                "title": "Show depth in one activity",
                "detail": f"Link one activity to a program offered by {name}.",
            }
        ],
    }
