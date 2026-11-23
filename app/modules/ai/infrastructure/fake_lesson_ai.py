"""Fake answers of the lesson AI (`lms_tutor_reply`, `lms_video_checks`)."""

import re
from typing import Any

_PART = re.compile(r'<part number="(\d+)">(.*?)</part>', re.S)
_LESSON = re.compile(r'<lesson title="([^"]*)">', re.S)


def build_lesson_ai_document(
    schema_name: str, system: str, messages: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a deterministic document, or None for another schema."""
    if schema_name == "lms_tutor_reply":
        found = _LESSON.search(system)
        title = found.group(1) if found else "this lesson"
        last = str(messages[-1]["content"]) if messages else ""
        return {
            "reply": (
                f"(fake tutor) Let us think it through. Which part of «{title}» "
                f"talks about «{' '.join(last.split()[:8])}»? What would you try "
                "first?"
            )
        }
    if schema_name == "lms_video_checks":
        text = str(messages[-1]["content"]) if messages else ""
        parts = _PART.findall(text)
        checks = [
            {
                "part": int(number),
                "question": f"What comes next after: «{' '.join(body.split()[:8])}»?",
                "options": [
                    {"text": "The idea is applied to an example", "correct": True},
                    {"text": "The video ends", "correct": False},
                    {"text": "An unrelated topic starts", "correct": False},
                ],
                "explanation": "The speaker explains an idea, then applies it.",
            }
            for number, body in parts
        ]
        cards = [
            {"front": f"Key idea {i + 1}", "back": " ".join(body.split()[:12])}
            for i, (_, body) in enumerate(parts[:3])
        ]
        return {"checks": checks, "cards": cards}
    return None
