"""Ports of the AI request registry and the published prompt defaults."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """A registered request as stored by the last publish of the code."""

    id: str
    owner_app: str
    task: str
    template_id: str
    pipeline: str
    args_schema: Mapping[str, Any] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    summary: str = ""
    published_at: datetime | None = None
    retired: bool = False
    code_version: int = 0


@dataclass(frozen=True, slots=True)
class PromptDefault:
    """The hash, version and text of a slot's built-in as last published."""

    task: str
    name: str
    version: int
    hash: str
    text: str = ""


class AiRequestRepository(Protocol):
    """The request registry of the open transaction."""

    async def list(
        self,
        *,
        owner_app: str | None = None,
        pipeline: str | None = None,
        include_retired: bool = False,
    ) -> list[RequestRecord]:
        """The registered requests, filtered; retired ones only when asked."""
        ...

    async def get(self, request_id: str) -> RequestRecord | None:
        """One registered request, or None."""
        ...

    async def upsert(self, record: RequestRecord) -> None:
        """Insert or replace a request by id."""
        ...

    async def retire_except(self, request_ids: set[str]) -> int:
        """Retire every request whose id is not listed; how many changed."""
        ...


class PromptDefaultRepository(Protocol):
    """The published built-in text hashes of the open transaction."""

    async def get(self, task: str, name: str) -> PromptDefault | None:
        """The stored default of a slot, or None."""
        ...

    async def upsert(self, default: PromptDefault, updated_at: datetime) -> None:
        """Insert or replace the default of a slot."""
        ...
