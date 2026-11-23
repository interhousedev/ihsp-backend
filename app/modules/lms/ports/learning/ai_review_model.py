"""Ports: the model and the web search behind the AI review block."""

from collections.abc import Sequence
from typing import Protocol

from app.modules.lms.domain.learning.ai_review import ReviewAnswer
from app.shared.actor import Actor


class AiReviewModel(Protocol):
    """One structured model call per student turn."""

    async def answer(
        self, *, system: str, messages: Sequence[dict[str, object]]
    ) -> ReviewAnswer:
        """Return the model's answer, validated against `ReviewAnswer`."""
        ...

    async def finalize(self, source: str) -> str | None:
        """Return the OpenUI source fenced and validated (repaired when needed)."""
        ...


class AiReviewWeb(Protocol):
    """Web search for a review; returns an empty string when it cannot search."""

    async def search(self, actor: Actor, *, query: str, locale: str) -> str:
        """Return the hits as plain text (title, URL, snippet)."""
        ...
