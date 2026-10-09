"""Use case: run a failed or canceled output again."""

from datetime import datetime
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import (
    REVISE_KEY,
    content_bytes,
    fresh_estimate,
    kick_generation,
    reserved,
    revision_estimate,
)
from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.enums import ArtifactStatus
from app.modules.notebooks.domain.errors import ArtifactNotReadyError
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

RETRYABLE = frozenset({ArtifactStatus.FAILED, ArtifactStatus.CANCELED})


def _reset(artifact: Artifact, now: datetime) -> None:
    """Back to a fresh `queued` row; `attempts` keeps counting."""
    artifact.status = ArtifactStatus.QUEUED
    artifact.error = None
    artifact.content = None
    artifact.refs_index = None
    artifact.sampled = False
    artifact.model = None
    artifact.tokens_in = None
    artifact.tokens_out = None
    artifact.tokens_cached = None
    artifact.weighted = None
    artifact.cost_micro = None
    artifact.progress = None
    artifact.started_at = None
    artifact.finished_at = None
    artifact.viewed_at = None
    artifact.updated_at = now


class RetryArtifact:
    """Queues a failed or canceled output again (it counts as a new request)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        budget: NotebookBudget,
        quota: QuotaService,
        kicker: TaskKicker,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.budget = budget
        self.quota = quota
        self.kicker = kicker
        self.clock = clock
        self.settings = settings

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> Artifact:
        """`failed` or `canceled` -> `queued`, and start the job again.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            ArtifactNotReadyError: The output is neither failed nor canceled.
            LimitReachedError: The weighted-token budget is used up.
            QuotaExceededError: The daily count of the kind is used up.
            BusyError: Too many outputs are generating already.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            if artifact.status not in RETRYABLE:
                raise ArtifactNotReadyError()
            course = notebook.is_course_workspace
            await self.budget.pool(course).require(
                actor.user_id, await self._estimate(uow, artifact)
            )
            if course:  # the one who retries pays this run
                artifact.requested_by = actor.user_id
            quota = self.quota.pool(course)
            async with reserved(quota, actor.user_id, artifact.kind, artifact.id):
                _reset(artifact, self.clock.now())
                await uow.artifacts.save(artifact)
                kick_generation(uow, self.kicker, artifact.id)
                await uow.commit()
        return artifact

    async def _estimate(self, uow: NotebooksUnitOfWork, artifact: Artifact) -> int:
        """Weighted estimate of running the output again."""
        if REVISE_KEY in artifact.options:
            parent = (
                await uow.artifacts.get(artifact.parent_id)
                if artifact.parent_id
                else None
            )
            slides = (parent.content or {}).get("slides", []) if parent else []
            return revision_estimate(content_bytes(slides))
        handler = handler_for(artifact.kind)
        options = handler.parse_options(dict(artifact.options))
        found = await uow.sources.get_many(artifact.source_ids)
        sources = [source for source in found if source.usable]
        return fresh_estimate(
            handler, options, sources, self.settings.notebooks.studio_context_tokens
        )
