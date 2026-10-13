"""The usage ledger: one event per model call (tokens, cost, who, what, success).

Recorded by the gateway decorators (see `infrastructure/recording_gateways.py`), so a
call is counted whatever module makes it. The feature is the product surface a task
belongs to; the task itself is the AI task (`app.shared.ai_tasks.AiTask`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.usage_context import (
    ROLE_ADMIN,
    ROLE_STAFF,
    ROLE_STUDENT,
    ROLE_SYSTEM,
    ROLE_TEACHER,
)

UNKNOWN_TASK = "unknown"
ROLES: tuple[str, ...] = (
    ROLE_STUDENT,
    ROLE_TEACHER,
    ROLE_ADMIN,
    ROLE_STAFF,
    ROLE_SYSTEM,
)

FEATURES: tuple[str, ...] = (
    "assistant",
    "notebook_chat",
    "notebook_prep",
    "studio",
    "lms_author",
    "web_search",
    "embedding",
    "academic",
    "other",
)

_FEATURE_OF: dict[str, str] = {
    "student_chat": "assistant",
    "student_chat_smart": "assistant",
    "admin_chat": "assistant",
    "chat_summary": "assistant",
    "context_compact": "notebook_chat",
    "notebook_chat": "notebook_chat",
    "source_guide": "notebook_prep",
    "notebook_summary": "notebook_prep",
    "source_labels": "notebook_prep",
    "studio_report": "studio",
    "studio_mind_map": "studio",
    "studio_flashcards": "studio",
    "studio_quiz": "studio",
    "studio_data_table": "studio",
    "studio_slides": "studio",
    "studio_slides_revise": "studio",
    "studio_infographic": "studio",
    "lms_authoring": "lms_author",
    "web_search": "web_search",
    "discover": "web_search",
    "embedding": "embedding",
    "subject_translate": "academic",
    "retrieval_plan": "notebook_chat",
    "query_decompose": "notebook_chat",
    "studio_faithfulness": "studio",
}


def feature_of(task: str) -> str:
    """The product surface of a task (``other`` for a call without a task)."""
    return _FEATURE_OF.get(task, "other")


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One model call as the ledger keeps it."""

    occurred_at: datetime
    user_id: UUID | None
    role: str
    task: str
    feature: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int | None
    cost_micro: int | None
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Totals:
    """Sums of ledger events: tokens, calls, failed calls and cost."""

    tokens_in: int = 0
    tokens_out: int = 0
    cached: int = 0
    calls: int = 0
    failed: int = 0
    cost_micro: int = 0


@dataclass(frozen=True, slots=True)
class GroupTotals:
    """The totals of one group key (a day, a task, ...) within one feature."""

    key: str
    feature: str
    totals: Totals


@dataclass(frozen=True, slots=True)
class UserTotals:
    """The totals of one user and the role of their latest call."""

    user_id: UUID
    role: str
    totals: Totals


@dataclass(frozen=True, slots=True)
class Counts:
    """Tokens and cost read from a provider's usage object."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int | None
    cost_micro: int | None


def counts_of(usage: Mapping[str, Any] | None) -> Counts:
    """Read the usage of a gateway answer; missing numbers count as zero or None.

    The gateways report ``input``, ``output``, ``cached`` and ``cost_micro``. An
    embedding batch reports ``input`` only (its tokens); a reasoning count is kept
    when a provider sends one.
    """
    data = usage or {}
    return Counts(
        input_tokens=_int(data.get("input")),
        output_tokens=_int(data.get("output")),
        cached_tokens=_int(data.get("cached")),
        reasoning_tokens=_optional_int(data.get("reasoning")),
        cost_micro=_optional_int(data.get("cost_micro")),
    )


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _int(value)
