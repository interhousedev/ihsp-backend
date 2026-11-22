"""Deterministic fake documents for admission career exploration.

They read the `[major] code: name` and `[item:<id>]` lines of the request so the
fit and the spike evidence point at real rows when the app runs without a key.
"""

import re
from collections.abc import Sequence
from typing import Any

PROFESSIONS_SCHEMA = "career_professions"
MAJORS_SCHEMA = "career_majors"
SPIKE_SCHEMA = "career_spike"
PROFESSION_FILL_SCHEMA = "career_profession_fill"
_TITLE = re.compile(r"^\[title\] (.+)$", re.MULTILINE)

_MAJOR = re.compile(r"^\[major\] ([a-z0-9_]+)", re.MULTILINE)
_ITEM = re.compile(r"^\[item:([0-9a-f-]{36})\]", re.MULTILINE)
_PROFESSIONS = (
    ("Software engineer", "You enjoy building things and solving puzzles."),
    ("Data scientist", "You like finding patterns and explaining them."),
    ("Biomedical researcher", "You are curious about how living things work."),
)


def _text(messages: Sequence[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


def build_career_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a schema-valid career document, else None."""
    if schema_name == PROFESSIONS_SCHEMA:
        return {
            "professions": [{"title": t, "reason": r} for t, r in _PROFESSIONS],
        }
    if schema_name == PROFESSION_FILL_SCHEMA:
        found = _TITLE.search(_text(messages))
        title = found.group(1) if found else "Profession"
        return {
            "name_en": title,
            "name_ru": title,
            "name_uz": title,
            "description_en": f"{title}: a role that combines skills and judgment.",
            "description_ru": f"{title}: роль, сочетающая навыки и суждение.",
            "description_uz": f"{title}: koʻnikma va mulohazani birlashtiruvchi kasb.",
            "isco_id": "2512",
            "related_fields": ["computer_science"],
            "ai_exposure": 0.4,
            "salary_band": "high",
        }
    if schema_name == MAJORS_SCHEMA:
        codes = list(dict.fromkeys(_MAJOR.findall(_text(messages))))[:5]
        return {
            "fit": [
                {
                    "code": code,
                    "score": 90 - 10 * rank,
                    "reason": "Matches the interests in your answers.",
                }
                for rank, code in enumerate(codes)
            ]
        }
    if schema_name == SPIKE_SCHEMA:
        items = list(dict.fromkeys(_ITEM.findall(_text(messages))))[:2]
        return {
            "title": "Building tools that help people learn",
            "summary": "Your activities show a steady focus on making and teaching.",
            "evidence": [
                {"item_id": item, "note": "Shows the focus in practice."}
                for item in items
            ],
            "gaps": ["Add one result with a number, such as people reached."],
        }
    return None
