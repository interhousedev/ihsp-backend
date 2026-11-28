"""Fake answers of the lesson AI (tutor reply, coach reply, video checks)."""

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
    if schema_name == "lms_coach_reply":
        return {
            "message": "(fake coach) What is the first thing the task asks you find?",
            "hint_level": 0,
            "ask_back": True,
        }
    if schema_name == "lms_badge_draft":
        return {
            "template": "first_lesson",
            "days": 14,
            "count": 5,
            "name_uz": "Birinchi dars",
            "name_ru": "Первый урок",
            "name_en": "First lesson",
            "description_uz": "Birinchi darsni tugatdi.",
            "description_ru": "Прошёл первый урок.",
            "description_en": "Finished the first lesson.",
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
