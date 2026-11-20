"""AI requests: a registered call (`owner.task.name` id) bound to one task and template.

A request names its task (so its pipeline follows from the task), one prompt slot
as its template, the JSON schema of its arguments and the tools it may use. Every
prompt slot without a declared request gets an auto-registered spec owned by `ai`.
Pure: no I/O; the application layer stores and runs them.
"""

import difflib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.ai.domain.prompt_registry import PromptSlot
from app.shared.ai_tasks import AiTask, pipeline_of
from app.shared.base_error import NotFoundError, ValidationFailedError

AUTO_OWNER = "ai"
_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}$")
_CHARS_PER_TOKEN = 4


class AiRequestNotFoundError(NotFoundError):
    """No registered request has the id (HTTP 404)."""

    code = "admin/ai-request-not-found"
    message_key = "admin-ai-request-not-found"


class AiRequestArgsInvalidError(ValidationFailedError):
    """The arguments do not match the request's schema (HTTP 422)."""

    code = "admin/ai-request-args-invalid"
    message_key = "admin-ai-request-args-invalid"


class AiRequestDuplicateError(Exception):
    """Two specs claim one request id; the process refuses to start."""


@dataclass(frozen=True, slots=True)
class AiRequestSpec:
    """One registered AI call: its id, owner, task, template, args and tools."""

    id: str
    owner_app: str
    task: str
    template: PromptSlot
    args_schema: Mapping[str, Any] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        """Reject ids that are not `owner.task.name` in lowercase identifiers."""
        if not _ID.match(self.id):
            raise ValueError(f"invalid request id: {self.id!r}")

    @property
    def pipeline(self) -> str:
        """The pipeline of the task (routing and analytics group by it)."""
        return pipeline_of(AiTask(self.task))

    @property
    def template_id(self) -> str:
        """`<task>/<name>`: the prompt slot the request renders."""
        return f"{self.template.task}/{self.template.name}"


def estimate_tokens(text: str) -> int:
    """A rough token count (a quarter of the characters, rounded up)."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def unified_diff(old: str, new: str, old_label: str, new_label: str) -> str:
    """The unified diff of two prompt texts; empty when they are equal."""
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=old_label,
        tofile=new_label,
    )
    return "".join(lines)


def build_catalog(
    slots: Iterable[PromptSlot], declared: Sequence[AiRequestSpec]
) -> list[AiRequestSpec]:
    """The declared specs, then one auto spec for each slot none of them renders."""
    seen: set[str] = set()
    for spec in declared:
        if spec.id in seen:
            raise AiRequestDuplicateError(spec.id)
        seen.add(spec.id)
    covered = {(s.template.task, s.template.name) for s in declared}
    auto = [
        AiRequestSpec(
            id=f"{AUTO_OWNER}.{slot.task}.{slot.name}",
            owner_app=AUTO_OWNER,
            task=slot.task,
            template=slot,
            summary=slot.summary,
        )
        for slot in slots
        if (slot.task, slot.name) not in covered
    ]
    for spec in auto:
        if spec.id in seen:
            raise AiRequestDuplicateError(spec.id)
        seen.add(spec.id)
    return [*declared, *auto]


@dataclass(frozen=True, slots=True)
class AiRequestInfo:
    """A published request with the state of its template's prompt versions."""

    id: str
    owner_app: str
    task: str
    pipeline: str
    template_id: str
    args_schema: Mapping[str, Any]
    tools: tuple[str, ...]
    summary: str
    published_at: datetime | None
    retired: bool
    active_version: int  # the active text of the template (0: the built-in)
    code_version: int  # the version that recorded the last published built-in
    code_changed_since_active: bool  # an administrator's text predates the built-in


@dataclass(frozen=True, slots=True)
class PromptDiff:
    """The difference between two versions of a prompt slot (0 is the built-in)."""

    task: str
    name: str
    locale: str
    from_version: int
    to_version: int
    diff: str
    chars_delta: int
    tokens_delta: int
