"""Ports: the stored prompt versions, the prompt rewriter and the analytics reader."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.ai.domain.prompt_registry import PromptRef, PromptVersion


class PromptVersionLoader(Protocol):
    """Reads the active versions for the registry's cache (its own session)."""

    async def active(self) -> Sequence[PromptVersion]:
        """Every active version."""
        ...


class PromptVersionRepository(Protocol):
    """The versions of the open transaction."""

    async def history(self, task: str, name: str) -> list[PromptVersion]:
        """Every version of a slot, every locale, newest first."""
        ...

    async def get_version(
        self, task: str, name: str, locale: str, version: int
    ) -> PromptVersion | None:
        """One stored version of a slot and locale, or None."""
        ...

    async def active(self, task: str | None = None) -> list[PromptVersion]:
        """The active versions (of one task when given)."""
        ...

    async def next_version(self, task: str) -> int:
        """The number the next version of the task gets (versions count per task)."""
        ...

    async def add(self, version: PromptVersion) -> None:
        """Insert a version (inactive; `activate` makes it the one)."""
        ...

    async def activate(self, task: str, name: str, locale: str, version: int) -> bool:
        """Make one version the active one of its slot and locale; False if missing."""
        ...

    async def deactivate(self, task: str, name: str, locale: str) -> int:
        """Deactivate the slot's versions for the locale; return how many were."""
        ...


class PromptRewriter(Protocol):
    """Puts the active prompt versions of a task into a system prompt."""

    async def rewrite(self, task: str | None, system: str) -> tuple[str, PromptRef]:
        """The system prompt to send, and what it used (version 0: built-ins)."""
        ...


@dataclass(frozen=True, slots=True)
class PromptCallStats:
    """Ledger figures of one task and prompt version (0 built-in) in a period."""

    task: str
    version: int
    calls: int
    failed: int
    p50_ms: float | None
    p95_ms: float | None
    input_tokens: int
    output_tokens: int
    cost_micro: int


@dataclass(frozen=True, slots=True)
class PromptRatingStats:
    """Thumbs on the assistant messages one task and prompt version wrote."""

    task: str
    version: int
    ratings: int
    average: float


@dataclass(frozen=True, slots=True)
class PromptCallTrace:
    """One ledger row of a model call: metadata only, never any text."""

    occurred_at: datetime
    task: str
    model: str
    version: int
    input_tokens: int
    output_tokens: int
    cost_micro: int | None
    latency_ms: int | None
    success: bool
    error: str | None


class PromptAnalyticsReader(Protocol):
    """Aggregates the usage ledger and the message ratings by prompt version."""

    async def calls(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptCallStats]:
        """Calls in [start, end) grouped by task and version."""
        ...

    async def ratings(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptRatingStats]:
        """Rated assistant messages in [start, end) grouped by task and version."""
        ...

    async def trace(
        self, task: str, version: int | None, limit: int
    ) -> list[PromptCallTrace]:
        """The latest calls of a task (of one prompt version when given)."""
        ...
