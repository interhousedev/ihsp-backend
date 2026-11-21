"""Adapters of the admission `PromptSource` port."""

from typing import Protocol

from app.modules.admission.infrastructure.ai.prompts import (
    alignment_map,
    app_review,
    career,
    essay_flow,
    essay_review,
    essays,
    goal_plan,
    item_grade,
    items,
    list_brief,
    list_suggest,
    opportunity_intake,
    opportunity_plan,
    profile_words,
    research,
    tasks_suggest,
    uni_advice,
)
from app.shared.ai_tasks import AiTask

BUILTIN_PROMPTS: dict[tuple[str, str], str] = {
    (AiTask.ADMIT_ITEM_REVIEW.value, "system"): items.REVIEW_SYSTEM,
    (AiTask.ADMIT_ITEM_REVIEW.value, "strict"): items.REVIEW_STRICT,
    (AiTask.ADMIT_ITEM_INTERVIEW.value, "system"): items.INTERVIEW_SYSTEM,
    (AiTask.ADMIT_ITEM_REWRITE_FIX.value, "system"): items.REWRITE_FIX_SYSTEM,
    (AiTask.ADMIT_PROFILE_WORDS.value, "system"): profile_words.SYSTEM,
    (AiTask.ADMIT_ALIGNMENT_MAP.value, "system"): alignment_map.SYSTEM,
    (AiTask.ADMIT_ALIGNMENT_REFRESH.value, "system"): alignment_map.SYSTEM,
    (AiTask.ADMIT_UNIVERSITY_RESEARCH.value, "system"): research.SYSTEM,
    (AiTask.ADMIT_GOAL_PLAN.value, "system"): goal_plan.SYSTEM,
    (AiTask.ADMIT_OPPORTUNITY_INTAKE.value, "system"): opportunity_intake.SYSTEM,
    (AiTask.ADMIT_OPPORTUNITY_PLAN.value, "system"): opportunity_plan.SYSTEM,
    **{
        (AiTask.ADMIT_ESSAY_COACH.value, name): text
        for name, text in essays.PROMPTS.items()
    },
    (AiTask.ADMIT_ESSAY_REVIEW.value, "base"): essay_review.BASE,
    (AiTask.ADMIT_ESSAY_UNI_REVIEW.value, "uni"): essay_review.UNI,
    (AiTask.ADMIT_ESSAY_PRACTICE.value, "practice"): essay_flow.PRACTICE,
    (AiTask.ADMIT_ESSAY_DEEP_READ.value, "deep_read"): essay_flow.DEEP_READ,
    (AiTask.ADMIT_PROMPT_GROUP_LABEL.value, "group_label"): essay_flow.GROUP_LABEL,
    **{
        (task.value, "system"): app_review.SECTION_SYSTEMS[key]
        for key, task in app_review.SECTION_TASKS.items()
    },
    (AiTask.ADMIT_APP_REVIEW_LEAD.value, "system"): app_review.LEAD_SYSTEM,
    (AiTask.ADMIT_CAREER_PROFESSIONS.value, "system"): career.PROFESSIONS,
    (AiTask.ADMIT_CAREER_MAJORS.value, "system"): career.MAJORS,
    (AiTask.ADMIT_CAREER_SPIKE.value, "system"): career.SPIKE,
    (AiTask.ADMIT_UNI_ADVICE.value, "system"): uni_advice.SYSTEM,
    (AiTask.ADMIT_LIST_SUGGEST.value, "system"): list_suggest.SYSTEM,
    (AiTask.ADMIT_LIST_BRIEF.value, "system"): list_brief.SYSTEM,
    (AiTask.ADMIT_TASKS_SUGGEST.value, "system"): tasks_suggest.SYSTEM,
    (AiTask.ADMIT_ACTIVITY_GRADE.value, "system"): item_grade.SYSTEM,
}


class _Resolved(Protocol):
    @property
    def text(self) -> str:
        """The prompt text."""
        ...


class _Registry(Protocol):
    async def resolve(
        self, task: str, name: str, locale: str, default: str | None = None
    ) -> _Resolved:
        """Resolve a prompt."""
        ...


class BuiltinPrompts:
    """The built-in texts only (tests and processes without a registry)."""

    async def text(self, task: AiTask, name: str, locale: str) -> str:
        """Return the built-in text."""
        return BUILTIN_PROMPTS[(task.value, name)]


class RegistryPrompts:
    """The active version of the prompt registry, else the built-in text."""

    def __init__(self, registry: _Registry) -> None:
        """Keep the registry."""
        self._registry = registry

    async def text(self, task: AiTask, name: str, locale: str) -> str:
        """Return the active text of the slot for the locale."""
        resolved = await self._registry.resolve(task.value, name, locale)
        return resolved.text
