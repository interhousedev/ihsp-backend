"""The task of a presentation plan (PLAN): a slide outline, not the deck itself.

The common Studio system prompt sets the language. The outline has the shape of a
deck (a title slide, the content, a summary) so the confirmed plan can be followed
slide by slide.
"""

from typing import Final

from app.modules.notebooks.domain.prompts.common import focus_clause

from pydantic import BaseModel, Field

PLAN_SCHEMA_NAME: Final = "nb_slides_plan"
PLAN_MAX_TOKENS: Final = 2_000

_TEMPLATE: Final = """\
Plan a slide deck from the sources: write its outline only, not the slides. Plan \
about {count} slides (at most {limit}). The first slide is the title slide, the \
last one sums up the key takeaways; the slides between follow the sources in their \
order, one idea per slide.

For every slide give a specific `title` (at most 8 words, no numbering) and 2 to 5 \
`bullets`: short phrases that say what the slide will show. Plain text only, no \
Markdown and no citation markers. Fill `title` of the plan with the topic of the \
deck (at most 8 words)."""


class PlanSlideOut(BaseModel):
    """One planned slide."""

    title: str = Field(description="At most 8 words.")
    bullets: list[str] = Field(description="2 to 5 short phrases.")


class PlanOut(BaseModel):
    """The outline of a deck."""

    title: str = Field(description="The topic of the deck, at most 8 words.")
    slides: list[PlanSlideOut]


def plan_task(*, count: int, limit: int, prompt: str | None) -> str:
    """The task text of an outline of about `count` slides."""
    return _TEMPLATE.format(count=count, limit=limit) + focus_clause(prompt)
