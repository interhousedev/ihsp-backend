"""Result types of the use cases (entities plus the extras an endpoint needs)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.notebooks.domain.entities import (
    Artifact,
    NotebookMessage,
    Passage,
    Source,
)
from app.shared.base_error import BaseError


@dataclass(frozen=True, slots=True)
class UsagePartView:
    """Weighted tokens against a limit."""

    used: int
    limit: int
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class QuotaView:
    """Daily count of outputs against a limit."""

    used: int
    limit: int
    resets_at: datetime


@dataclass(frozen=True, slots=True)
class NotebookUsageView:
    """`NotebookUsage` of § 4.4: budget, quotas and the generating counter."""

    session: UsagePartView
    day: UsagePartView
    quotas: dict[str, QuotaView]  # artifacts | audio_overview | slides | infographic
    generating: int
    generating_limit: int


@dataclass(frozen=True, slots=True)
class TurnView:
    """The answer to one question: both messages and the fresh usage."""

    user_message: NotebookMessage
    assistant_message: NotebookMessage
    usage: NotebookUsageView
    action: dict[str, Any] | None = None  # P2: a proposed Studio output


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One server-sent event: `message`, `delta`, `citation`, `done` or `error`."""

    name: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RejectedSource:
    """An item of a batch that was not added."""

    index: int
    error: BaseError


@dataclass(slots=True)
class AddSourcesResult:
    """`201 {items, rejected}` of `POST /sources`."""

    items: list[Source] = field(default_factory=list)
    rejected: list[RejectedSource] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PassageDetailView:
    """A passage with its source and the passages around it."""

    passage: Passage
    source: Source
    before: list[Passage]
    after: list[Passage]


@dataclass(frozen=True, slots=True)
class ArtifactDetailView:
    """An output with the student's progress in it."""

    artifact: Artifact
    progress_state: dict[str, Any] | None
