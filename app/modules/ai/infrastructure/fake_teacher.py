"""Fake documents of the teacher AI tasks (no language model, `fake` mode)."""

import re
from collections.abc import Sequence
from typing import Any

from app.modules.ai.infrastructure.fake_sources import last_user_text

Document = dict[str, Any]
_TOPIC = re.compile(r"<topic>\n(.*?)\n</topic>", re.DOTALL)
_COUNT = re.compile(r"exactly (\d+) questions")
_MINUTES = re.compile(r"duration: (\d+) minutes")


def _topic(text: str) -> str:
    found = _TOPIC.search(text)
    return found.group(1).strip()[:80] if found else "Demo topic"


def build_teacher_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> Document | None:
    """Return a demo document for a teacher schema, or None for another schema."""
    text = last_user_text(messages)
    topic = _topic(text)
    if schema_name == "teacher_questions":
        found = _COUNT.search(text)
        count = int(found.group(1)) if found else 3
        return {
            "questions": [
                {
                    "question": f"Demo question {n} about {topic}?",
                    "options": ["A", "B", "C", "D"] if n % 2 else [],
                    "answer": "A" if n % 2 else f"Demo answer {n}",
                    "explanation": f"Demo explanation {n}.",
                }
                for n in range(1, count + 1)
            ]
        }
    if schema_name == "teacher_handout":
        return {
            "title": f"Handout: {topic}",
            "markdown": f"# Handout: {topic}\n\n## Key ideas\n\n- Demo idea\n\n"
            "## Practice\n\n1. Demo task",
        }
    if schema_name == "teacher_work_check":
        return {
            "summary": "Demo feedback on the work.",
            "score": 7.0,
            "strengths": ["Clear structure"],
            "issues": ["Few examples"],
            "suggestions": ["Add an example"],
        }
    if schema_name == "teacher_ai_check":
        return {"ai_likelihood": 0.2, "signals": ["Demo signal"]}
    if schema_name == "teacher_lesson_plan":
        found = _MINUTES.search(text)
        minutes = found.group(1) if found else "45"
        return {
            "title": f"Lesson plan: {topic}",
            "markdown": (
                f"# Lesson plan: {topic}\n\n## Objectives\n\n- Demo objective\n\n"
                f"## Stages ({minutes} min)\n\n- Demo stage"
            ),
        }
    return None
