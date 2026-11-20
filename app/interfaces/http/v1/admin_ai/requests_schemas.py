"""Schemas of the AI request registry and prompt version routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.ai.domain.prompt_registry import PromptVersion
from app.modules.ai.domain.requests import AiRequestInfo, PromptDiff

from pydantic import BaseModel, Field


class RequestOut(BaseModel):
    """A request the code published, and the state of its prompt template."""

    id: str = Field(examples=["notebooks.studio_quiz.generate"])
    owner_app: str
    task: str
    pipeline: str
    template_id: str = Field(description="`<task>/<name>` of the prompt slot.")
    args_schema: dict[str, Any]
    tools: list[str]
    summary: str
    published_at: datetime | None
    retired: bool = Field(description="True once no code declares the request.")
    active_version: int = Field(
        description="The template version in force; 0 is built-in."
    )
    code_version: int = Field(description="The version that recorded the code's text.")
    code_changed_since_active: bool = Field(
        description="An administrator's text predates the latest code default."
    )

    @classmethod
    def of(cls, info: AiRequestInfo) -> "RequestOut":
        """From the domain view."""
        return cls(
            id=info.id,
            owner_app=info.owner_app,
            task=info.task,
            pipeline=info.pipeline,
            template_id=info.template_id,
            args_schema=dict(info.args_schema),
            tools=list(info.tools),
            summary=info.summary,
            published_at=info.published_at,
            retired=info.retired,
            active_version=info.active_version,
            code_version=info.code_version,
            code_changed_since_active=info.code_changed_since_active,
        )


class RequestsResponse(BaseModel):
    """The registered requests."""

    items: list[RequestOut]


class PromptVersionSummaryOut(BaseModel):
    """A stored version without its text."""

    version: int
    locale: str
    source: str = Field(description="`admin` (an administrator) or `code` (a deploy).")
    active: bool
    hash: str
    chars: int
    tokens_est: int = Field(description="About a quarter of the characters.")
    created_at: datetime
    created_by: UUID | None
    note: str
    has_diff: bool

    @classmethod
    def of(cls, version: PromptVersion) -> "PromptVersionSummaryOut":
        """From the domain version."""
        return cls(
            version=version.version,
            locale=version.locale,
            source=version.source,
            active=version.active,
            hash=version.hash,
            chars=version.chars,
            tokens_est=version.tokens_est,
            created_at=version.created_at,
            created_by=version.created_by,
            note=version.note,
            has_diff=bool(version.diff),
        )


class PromptVersionsResponse(BaseModel):
    """The versions of one slot, newest first."""

    items: list[PromptVersionSummaryOut]


class PromptDiffOut(BaseModel):
    """The unified diff between two versions of a slot (0 is the built-in)."""

    task: str
    name: str
    locale: str
    from_version: int
    to_version: int
    diff: str
    chars_delta: int
    tokens_delta: int

    @classmethod
    def of(cls, diff: PromptDiff) -> "PromptDiffOut":
        """From the domain diff."""
        return cls(
            task=diff.task,
            name=diff.name,
            locale=diff.locale,
            from_version=diff.from_version,
            to_version=diff.to_version,
            diff=diff.diff,
            chars_delta=diff.chars_delta,
            tokens_delta=diff.tokens_delta,
        )
