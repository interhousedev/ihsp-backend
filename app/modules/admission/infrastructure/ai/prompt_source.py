"""Adapters of the admission `PromptSource` port."""

from typing import Protocol

from app.modules.admission.infrastructure.ai.prompts import (
    alignment_map,
    goal_plan,
    items,
    profile_words,
    research,
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
