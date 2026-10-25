"""A deck outline: numbered slide titles with their bullets (PLAN).

A presentation plan is confirmed by the student before the deck is made; the deck's
options then carry the outline and the task block asks the model to follow it.
"""

from typing import Final

from pydantic import BaseModel, Field, field_validator

OUTLINE_TITLE_CHARS: Final = 120
OUTLINE_BULLET_CHARS: Final = 300
OUTLINE_BULLETS: Final = 8


class PlanSlide(BaseModel):
    """One slide of an outline: a title and up to 8 bullets."""

    title: str = Field(min_length=1, max_length=OUTLINE_TITLE_CHARS)
    bullets: list[str] = Field(default_factory=list, max_length=OUTLINE_BULLETS)

    @field_validator("bullets")
    @classmethod
    def _short_bullets(cls, value: list[str]) -> list[str]:
        return [item[:OUTLINE_BULLET_CHARS] for item in value]


def outline_text(slides: list[PlanSlide]) -> str:
    """The outline as numbered lines: ``1. Title`` then ``   - bullet``."""
    lines: list[str] = []
    for number, slide in enumerate(slides, start=1):
        lines.append(f"{number}. {slide.title}")
        lines.extend(f"   - {bullet}" for bullet in slide.bullets)
    return "\n".join(lines)


def outline_clause(slides: list[PlanSlide] | None) -> str:
    """The task text that makes the deck follow a confirmed outline ("" without)."""
    if not slides:
        return ""
    return (
        f"\n\nFollow this outline, which the student confirmed: exactly "
        f"{len(slides)} slides, in this order, with these titles. Develop each "
        "slide's bullets from the sources (keep their meaning, add facts and refs); "
        "choose the layout that fits each slide.\n"
        f"<outline>\n{outline_text(slides)}\n</outline>"
    )
