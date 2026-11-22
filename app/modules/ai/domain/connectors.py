"""Connectors (provider endpoints) and pipeline routes of the AI module.

A connector is a configured provider endpoint; its kind is code, its instances are
rows (or, for `openrouter`, `anthropic` and `exa`, the environment). Keys are never
part of these types: they live in Vault. A pipeline is a named group of AI tasks
(`app.shared.ai_tasks.PIPELINE_OF`); a route sends a pipeline to a connector, a model
and a reasoning effort.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.shared.ai_tasks import PIPELINE_OF, Pipeline, pipeline_of

__all__ = [
    "BUILTIN_IDS",
    "EFFORTS",
    "LANGFUSE_DEFAULT_HOST",
    "LANGFUSE_SECRET_ID",
    "TRACING_CAPTURE_DEFAULT",
    "MODEL_KINDS",
    "PIPELINE_OF",
    "SEARCH_KINDS",
    "UNTRACED_BY_DEFAULT",
    "Connector",
    "ConnectorKind",
    "EffectiveRoute",
    "Pipeline",
    "PipelineRoute",
    "ProbeResult",
    "TracingConfig",
    "default_connector_id",
    "default_tracing",
    "kind_fits",
    "pipeline_of",
    "valid_base_url",
    "valid_slug",
]


class ConnectorKind(StrEnum):
    """What a connector talks to."""

    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"
    EXA = "exa"


MODEL_KINDS: Final = frozenset(
    {
        ConnectorKind.OPENROUTER,
        ConnectorKind.ANTHROPIC,
        ConnectorKind.OPENAI_COMPATIBLE,
    }
)
SEARCH_KINDS: Final = frozenset({ConnectorKind.EXA})

# Made from the environment when no row has the id; a row overrides the environment.
BUILTIN_IDS: Final = (
    ConnectorKind.OPENROUTER.value,
    ConnectorKind.ANTHROPIC.value,
    ConnectorKind.EXA.value,
)
EFFORTS: Final = ("none", "minimal", "low", "medium", "high")

_SLUG = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class Connector:
    """One provider endpoint; `source` says where it comes from."""

    id: str
    kind: ConnectorKind
    title: str
    base_url: str | None
    enabled: bool
    has_secret: bool
    secret_last4: str | None
    builtin: bool
    source: Literal["env", "db"]


@dataclass(frozen=True, slots=True)
class PipelineRoute:
    """Where a pipeline's calls go at runtime; a null field falls through."""

    pipeline: Pipeline
    connector_id: str | None
    model: str | None
    reasoning_effort: str | None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    tracing_enabled: bool | None = None
    capture_content: bool | None = None

    @property
    def empty(self) -> bool:
        """True when every field falls through (the row can go)."""
        return (
            self.connector_id is None
            and self.model is None
            and self.reasoning_effort is None
            and self.tracing_enabled is None
            and self.capture_content is None
        )


@dataclass(frozen=True, slots=True)
class TracingConfig:
    """The Langfuse project set by Administration; the secret key is in Vault."""

    host: str
    public_key: str
    has_secret: bool
    secret_last4: str | None
    updated_at: datetime | None = None
    updated_by: UUID | None = None


# Vault path of the Langfuse secret key; not a valid connector slug, so no clash.
LANGFUSE_SECRET_ID: Final = "_langfuse"
# Langfuse API root shown before Administration sets a project.
LANGFUSE_DEFAULT_HOST: Final = "https://cloud.langfuse.com"
# Content capture of a pipeline that set nothing: prompts and answers stay home.
TRACING_CAPTURE_DEFAULT: Final = False
# Pipelines that read essays and applicant profiles: untraced unless switched on.
UNTRACED_BY_DEFAULT: Final = frozenset({Pipeline.ADMISSION})


def default_tracing(pipeline: Pipeline) -> bool:
    """Whether a pipeline's calls are traced when Administration set nothing."""
    return pipeline not in UNTRACED_BY_DEFAULT


@dataclass(frozen=True, slots=True)
class EffectiveRoute:
    """What one task's call uses. `runtime_*` tell which values the route set."""

    pipeline: Pipeline
    connector_id: str
    model: str
    reasoning_effort: str | None
    source: Literal["runtime", "env"]
    runtime_model: bool = False
    runtime_effort: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The answer of a connector test."""

    ok: bool
    latency_ms: int
    error: str | None


def valid_slug(value: str) -> bool:
    """True for a connector id: lowercase letters, digits, `_` and `-`."""
    return _SLUG.fullmatch(value) is not None


def valid_base_url(value: str, *, allow_plain_local: bool) -> bool:
    """An https URL; plain http only for localhost and only when allowed."""
    parts = urlsplit(value)
    if not parts.hostname or parts.username or parts.password:
        return False
    if parts.scheme == "https":
        return True
    return (
        allow_plain_local and parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS
    )


def kind_fits(kind: ConnectorKind, pipeline: Pipeline) -> bool:
    """Search pipelines take search connectors, every other pipeline model ones."""
    if pipeline is Pipeline.WEB_SEARCH:
        return kind in SEARCH_KINDS
    return kind in MODEL_KINDS


def default_connector_id(pipeline: Pipeline) -> str:
    """The built-in connector a pipeline uses when nothing else is set."""
    return (
        ConnectorKind.EXA.value
        if pipeline is Pipeline.WEB_SEARCH
        else ConnectorKind.OPENROUTER.value
    )
