"""A planned outline (sections with steps) matched against the draft outline.

The author assistant and the "Apply plan" button of the course workspace send a plan.
Applying it creates only what the draft does not have yet: a section or step is found
by its title, compared without case and extra spaces, and is never renamed, moved or
removed. This module is pure: it parses the plan and decides what is new.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from app.modules.lms.domain.authoring.course_rules import (
    TITLE_MAX_LENGTH,
    clean_title,
)
from app.modules.lms.domain.authoring.errors import PlanInvalidError
from app.modules.lms.domain.authoring.outline import Outline, sections_of

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

MAX_SECTIONS: Final = 30
MAX_STEPS_PER_SECTION: Final = 30
MAX_BRIEF_LENGTH: Final = 20_000


class PlanAction(StrEnum):
    """What applying the plan does with one section or step."""

    NEW = "new"
    EXISTS = "exists"


# - - - Parsing the plan - - -


class _StepInput(BaseModel):
    """One planned step as the caller sends it."""

    title: str
    brief: str | None = Field(default=None, max_length=MAX_BRIEF_LENGTH)


class _SectionInput(BaseModel):
    """One planned section as the caller sends it."""

    title: str
    steps: list[_StepInput] = Field(
        default_factory=list, max_length=MAX_STEPS_PER_SECTION
    )


_PLAN_ADAPTER: Final = TypeAdapter(list[_SectionInput])


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """A step of the plan with a clean title; ``brief`` may be empty."""

    title: str
    brief: str


@dataclass(frozen=True, slots=True)
class PlannedSection:
    """A section of the plan with a clean title."""

    title: str
    steps: tuple[PlannedStep, ...]


def parse_plan(sections: Sequence[Mapping[str, Any]]) -> list[PlannedSection]:
    """Validate a plan and return it with clean titles.

    Raises:
        PlanInvalidError: Wrong shape, no sections, more than 30 sections or 30 steps
            in a section, or a brief over 20,000 characters.
        TitleInvalidError: A title is empty or longer than 200 characters.
    """
    if not 1 <= len(sections) <= MAX_SECTIONS:
        raise _invalid([{"loc": ["sections"], "msg": "wrong number of sections"}])
    try:
        parsed = _PLAN_ADAPTER.validate_python(list(sections))
    except ValidationError as exc:
        raise _invalid(
            [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        ) from exc
    return [
        PlannedSection(
            title=clean_title(section.title),
            steps=tuple(
                PlannedStep(clean_title(step.title), (step.brief or "").strip())
                for step in section.steps
            ),
        )
        for section in parsed
    ]


def _invalid(errors: list[dict[str, Any]]) -> PlanInvalidError:
    return PlanInvalidError(
        params={
            "errors": errors,
            "max_sections": MAX_SECTIONS,
            "max_steps": MAX_STEPS_PER_SECTION,
            "max_brief": MAX_BRIEF_LENGTH,
            "max_title": TITLE_MAX_LENGTH,
        }
    )


# - - - Matching the plan with the draft - - -


@dataclass(slots=True)
class StepPlan:
    """What happens to one planned step; ``step_id`` is None for a new step."""

    title: str
    brief: str
    action: PlanAction
    step_id: UUID | None = None


@dataclass(slots=True)
class SectionPlan:
    """What happens to one planned section; ``section_id`` is None for a new one."""

    title: str
    action: PlanAction
    steps: list[StepPlan]
    section_id: str | None = None


def title_key(title: str) -> str:
    """Return the title without case and extra spaces, the key for matching."""
    return " ".join(title.split()).casefold()


def match_plan(
    outline: Outline,
    step_titles: Mapping[UUID, str],
    planned: Sequence[PlannedSection],
) -> list[SectionPlan]:
    """Decide for every planned section and step whether the draft has it already.

    Each planned item is matched against the draft only, so the result is the same for
    a dry run and for the real call. When the draft holds several sections with the
    same title the first one counts, and the same goes for steps inside a section.

    Args:
        outline: The current draft outline.
        step_titles: Draft titles of the steps in the outline, by step ID.
        planned: The parsed plan.
    """
    sections: dict[str, tuple[str, dict[str, UUID]]] = {}
    for section in sections_of(outline):
        steps: dict[str, UUID] = {}
        for raw in section["steps"]:
            step_id = UUID(raw)
            if step_id in step_titles:
                steps.setdefault(title_key(step_titles[step_id]), step_id)
        sections.setdefault(title_key(section["title"]), (section["id"], steps))
    return [_match_section(section, sections) for section in planned]


def _match_section(
    section: PlannedSection, existing: Mapping[str, tuple[str, dict[str, UUID]]]
) -> SectionPlan:
    found = existing.get(title_key(section.title))
    if found is None:
        return SectionPlan(
            section.title,
            PlanAction.NEW,
            [StepPlan(s.title, s.brief, PlanAction.NEW) for s in section.steps],
        )
    section_id, steps = found
    return SectionPlan(
        section.title,
        PlanAction.EXISTS,
        [_match_step(step, steps) for step in section.steps],
        section_id,
    )


def _match_step(step: PlannedStep, existing: Mapping[str, UUID]) -> StepPlan:
    step_id = existing.get(title_key(step.title))
    if step_id is None:
        return StepPlan(step.title, step.brief, PlanAction.NEW)
    return StepPlan(step.title, step.brief, PlanAction.EXISTS, step_id)
