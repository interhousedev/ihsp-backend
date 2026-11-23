"""A deterministic answer for the LMS AI review in fake mode.

It reads the mode and the criteria from the system prompt (the lines
`- <name> (0..<max>)` of <criteria>), so tests and local runs get the same review
for the same block. It never repeats the teacher's instructions.
"""

import re
from typing import Any, Final

_MODE: Final = re.compile(r"<mode>\s*(.*?)\s*</mode>", re.DOTALL)
_CRITERIA: Final = re.compile(r"<criteria>\s*(.*?)\s*</criteria>", re.DOTALL)
_LINE: Final = re.compile(r"^- (.+?) \(0\.\.([\d.]+)\)", re.MULTILINE)
_IMAGE: Final = re.compile(r"^Image: (.+)$", re.MULTILINE)


def build_ai_review_document(
    schema_name: str, system: str, messages: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the fake review answer, or None for another schema."""
    if schema_name != "lms_ai_review":
        return None
    mode_found = _MODE.search(system)
    mode = mode_found.group(1) if mode_found else ""
    empty: dict[str, Any] = {
        "questions": [],
        "summary": "",
        "scores": [],
        "strengths": [],
        "improvements": [],
        "images": [],
    }
    if mode.startswith("No work"):
        return {
            **empty,
            "kind": "chat",
            "message": "Upload your work and I will review it against the criteria.",
        }
    if mode.startswith("You may ask"):
        return {
            **empty,
            "kind": "question",
            "message": "Thanks! Before the review, a quick question.",
            "questions": ["What was the hardest part of this work for you?"],
        }
    criteria_found = _CRITERIA.search(system)
    lines = _LINE.findall(criteria_found.group(1) if criteria_found else "")
    images = _IMAGE.findall(_texts(messages))
    return {
        **empty,
        "kind": "review",
        "message": "Here is your review.",
        "summary": "A solid piece of work with clear room to grow.",
        "scores": [
            {
                "name": name,
                "score": round(float(top) * 0.8, 1),
                "comment": f"Good work on {name.lower()}.",
            }
            for name, top in lines
        ],
        "strengths": ["Clear structure", "Own examples"],
        "improvements": ["Add sources", "Check the conclusion"],
        "images": [{"file": n, "comment": "Clear and readable."} for n in images],
    }


def _texts(messages: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            out += [str(p.get("text", "")) for p in content if isinstance(p, dict)]
    return "\n".join(out)
