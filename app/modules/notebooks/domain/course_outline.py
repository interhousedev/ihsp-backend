"""The draft outline of a course as plain text for prompts (course workspaces)."""

from typing import Final

from app.shared.contracts.lms import CourseBrief

OUTLINE_MAX_CHARS: Final = 12_000  # a long outline is cut, never the whole prompt
STEP_TEXT_MAX_CHARS: Final = 24_000  # the draft of one step given as context
DESCRIPTION_MAX_CHARS: Final = 2_000
_CUT: Final = "\n[... cut ...]"


def _line(text: str) -> str:
    """One line: no line breaks, no runs of spaces."""
    return " ".join(text.split())


def cut(text: str, limit: int) -> str:
    """The text, or its first `limit` characters with a marker that it was cut."""
    if len(text) <= limit:
        return text
    return text[: max(limit - len(_CUT), 0)].rstrip() + _CUT


def outline_text(brief: CourseBrief) -> str:
    """Sections and steps with their ids, indented, in course order.

    Example::

        1. Algebra basics (section_id: s1)
           1.1 Variables (step_id: 0190...)
    """
    if not brief.sections:
        return "(the course has no sections yet)"
    lines: list[str] = []
    for number, section in enumerate(brief.sections, start=1):
        lines.append(
            f"{number}. {_line(section.title)} (section_id: {section.section_id})"
        )
        if not section.steps:
            lines.append("   (no steps yet)")
        for index, step in enumerate(section.steps, start=1):
            lines.append(
                f"   {number}.{index} {_line(step.title)} (step_id: {step.step_id})"
            )
    return cut("\n".join(lines), OUTLINE_MAX_CHARS)
