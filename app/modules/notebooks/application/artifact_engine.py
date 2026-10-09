"""Pieces shared by the Studio use cases: queued rows, reservations, error payloads."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.application.views import ArtifactDetailView
from app.modules.notebooks.domain.artifacts.handler import ArtifactHandler
from app.modules.notebooks.domain.artifacts.kind_support import CommonOptions
from app.modules.notebooks.domain.entities import (
    Artifact,
    ArtifactError,
    Notebook,
    Source,
)
from app.modules.notebooks.domain.enums import (
    ArtifactFailure,
    ArtifactKind,
    ArtifactStatus,
)
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
    OutputInvalidError,
)
from app.modules.notebooks.domain.limits import (
    ARTIFACT_TITLE_MAX_CHARS,
    CONTENT_MAX_BYTES,
    STUDIO_PROMPT_MAX_CHARS,
)
from app.modules.notebooks.domain.tokens import CHARS_PER_TOKEN, estimate_cost
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

from pydantic import BaseModel

GENERATE_TASK: Final = "notebooks.generate_artifact"
PROCESS_SOURCE_TASK: Final = "notebooks.process_source"
REVISE_KEY: Final = "revise"  # options["revise"] = {"changes": [...]}
REVISE_MAX_TOKENS: Final = 6_000  # a revision returns only the changed slides
ACTIVE: Final = frozenset({ArtifactStatus.QUEUED, ArtifactStatus.GENERATING})

ERROR_KEYS: Final = {
    ArtifactFailure.PROVIDER_ERROR: "notebooks-artifact-error-provider",
    ArtifactFailure.INVALID_OUTPUT: "notebooks-artifact-error-invalid-output",
    ArtifactFailure.NO_CONTENT: "notebooks-artifact-error-no-content",
    ArtifactFailure.LIMIT_REACHED: "notebooks-artifact-error-limit-reached",
    ArtifactFailure.TIMEOUT: "notebooks-artifact-error-timeout",
    ArtifactFailure.CANCELED: "notebooks-artifact-error-canceled",
}


def artifact_error(
    code: ArtifactFailure, params: dict[str, Any] | None = None
) -> ArtifactError:
    """The `artifacts.error` payload of a failure code."""
    return ArtifactError(
        code=code.value, message_key=ERROR_KEYS[code], params=params or {}
    )


def kick_generation(
    uow: NotebooksUnitOfWork, kicker: TaskKicker, artifact_id: UUID
) -> None:
    """Start `notebooks.generate_artifact` once the transaction commits."""
    uow.after_commit(partial(kicker.kick, GENERATE_TASK, artifact_id=str(artifact_id)))


@asynccontextmanager
async def reserved(
    quota: QuotaService, user_id: UUID, kind: ArtifactKind, artifact_id: UUID
) -> AsyncIterator[None]:
    """Count a request against the quotas; undo it if the body fails.

    Raises:
        QuotaExceededError: The daily count of the kind is used up.
        BusyError: Too many outputs are generating already.
    """
    await quota.reserve(user_id, kind, artifact_id)
    try:
        yield
    except BaseException:
        await quota.release(user_id, kind)
        await quota.finished(user_id, artifact_id)
        raise


def common_options(options: BaseModel) -> CommonOptions:
    """Narrow parsed options to the part every kind shares."""
    if not isinstance(options, CommonOptions):
        raise TypeError(f"expected common options, got {type(options).__name__}")
    return options


def clean_prompt(prompt: str | None) -> str | None:
    """The focus text trimmed; None when empty.

    Raises:
        InvalidOptionsError: The text is longer than 1 000 characters.
    """
    text = (prompt or "").strip()
    if len(text) > STUDIO_PROMPT_MAX_CHARS:
        raise InvalidOptionsError(
            params={
                "details": [f"prompt: at most {STUDIO_PROMPT_MAX_CHARS} characters"]
            },
            support_details="prompt is too long",
        )
    return text or None


def content_bytes(content: object) -> int:
    """Size of a document as it is stored (UTF-8 JSON)."""
    return len(json.dumps(content, ensure_ascii=False).encode())


def ensure_fits(content: object) -> None:
    """Raise `OutputInvalidError` when a document is over 512 KB."""
    if content_bytes(content) > CONTENT_MAX_BYTES:
        raise OutputInvalidError(
            [
                f"the document is larger than {CONTENT_MAX_BYTES // 1024} KB: "
                "write fewer or shorter items"
            ]
        )


def fresh_estimate(
    handler: ArtifactHandler,
    options: BaseModel,
    sources: list[Source],
    studio_context_tokens: int,
) -> int:
    """Weighted estimate of a new output: capped source text plus `max_tokens` x 5."""
    cap_chars = int(handler.input_cap_tokens(studio_context_tokens) * CHARS_PER_TOKEN)
    chars = min(sum(source.char_count for source in sources), cap_chars)
    return estimate_cost(chars, handler.max_tokens(options))


def revision_estimate(deck_chars: int) -> int:
    """Weighted estimate of a slide revision (the deck is sent, sources are not)."""
    return estimate_cost(deck_chars, REVISE_MAX_TOKENS)


def queued_artifact(
    *,
    notebook: Notebook,
    kind: ArtifactKind,
    title: str,
    options: dict[str, Any],
    prompt: str | None,
    source_ids: list[UUID],
    source_map: dict[str, str],
    now: datetime,
    report_format: str | None = None,
    parent_id: UUID | None = None,
) -> Artifact:
    """A new output in `queued` (not stored yet)."""
    return Artifact(
        id=new_id(),
        notebook_id=notebook.id,
        owner_id=notebook.owner_id,
        kind=kind,
        title=title[:ARTIFACT_TITLE_MAX_CHARS],
        created_at=now,
        updated_at=now,
        status=ArtifactStatus.QUEUED,
        format=report_format,
        options=options,
        prompt=prompt,
        source_ids=source_ids,
        source_map=source_map,
        parent_id=parent_id,
    )


def mark_canceled(artifact: Artifact, now: datetime) -> None:
    """Turn a queued or generating output into `canceled` (the job drops its result)."""
    artifact.status = ArtifactStatus.CANCELED
    artifact.error = artifact_error(ArtifactFailure.CANCELED)
    artifact.finished_at = now
    artifact.updated_at = now


def require_ready(artifact: Artifact, *kinds: ArtifactKind) -> dict[str, Any]:
    """Return the content of a ready output of one of the kinds.

    Raises:
        InvalidOptionsError: The action does not exist for this kind of output.
        ArtifactNotReadyError: The output is not `ready` (or has no content).
    """
    if artifact.kind not in kinds:
        raise InvalidOptionsError(
            params={"details": [f"kind: not available for {artifact.kind.value}"]},
            support_details="action does not fit the kind",
        )
    if artifact.status is not ArtifactStatus.READY or artifact.content is None:
        raise ArtifactNotReadyError()
    return artifact.content


def revise_changes(artifact: Artifact) -> list[dict[str, str]] | None:
    """The `changes` of a slide revision, None for an ordinary output."""
    revise = artifact.options.get(REVISE_KEY)
    if not isinstance(revise, dict):
        return None
    changes = revise.get("changes")
    return list(changes) if isinstance(changes, list) else None


async def detail_view(
    uow: NotebooksUnitOfWork, artifact: Artifact, user_id: UUID
) -> ArtifactDetailView:
    """The output with the student's saved progress in it."""
    progress = await uow.progress.get(artifact.id, user_id)
    return ArtifactDetailView(
        artifact=artifact, progress_state=progress.state if progress else None
    )
