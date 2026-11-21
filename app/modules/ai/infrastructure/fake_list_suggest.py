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


LIST_BRIEF_SCHEMA = "list_brief"

_BRIEF_TEXT = {
    "ru": (
        "Список склоняется к амбициозным вузам",
        "В списке мало вузов, куда вы поступите с высокой вероятностью. "
        "Добавьте вуз с запасом и один-два реалистичных, чтобы список был устойчивым.",
        "Подходит как запасной вариант по опубликованному проценту приёма.",
        ("Добавьте один запасной вуз", "Сверьте сроки подачи по новым вузам"),
    ),
    "uz": (
        "Roʼyxat oʼta qiyin universitetlarga ogʼgan",
        "Roʼyxatda qabul ehtimoli yuqori universitetlar kam. "
        "Barqaror boʼlishi uchun zaxira va bir-ikki real variant qoʼshing.",
        "Eʼlon qilingan qabul foiziga koʼra zaxira variant sifatida mos.",
        (
            "Bitta zaxira universitet qoʼshing",
            "Yangi universitetlar muddatlarini tekshiring",
        ),
    ),
    "en": (
        "Your list leans toward reach",
        "Few schools on your list are ones you are likely to get into. "
        "Add a safety and one or two realistic targets to make the list resilient.",
        "Fits as a safety by its published admit rate.",
        ("Add one safety school", "Check the deadlines of the new schools"),
    ),
}


def build_list_brief_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a schema-valid list brief document in the request language, else None."""
    if schema_name != LIST_BRIEF_SCHEMA:
        return None
    text = "\n".join(str(m.get("content", "")) for m in messages)
    lang = re.search(r"^Language: (\w+)", text, re.MULTILINE)
    headline, diagnosis, reason, steps = _BRIEF_TEXT.get(
        lang.group(1) if lang else "en", _BRIEF_TEXT["en"]
    )
    numbers = list(dict.fromkeys(int(n) for n in _CANDIDATE.findall(text)))[:3]
    return {
        "headline": headline,
        "diagnosis": diagnosis,
        "suggestions": [{"candidate": n, "reason": reason} for n in numbers],
        "next_steps": list(steps),
    }
