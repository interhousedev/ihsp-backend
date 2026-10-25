"""Use case: regenerate only the named slides of a deck as a new output (§ 3.4.6)."""

from typing import Any, Final
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import (
    REVISE_KEY,
    content_bytes,
    kick_generation,
    queued_artifact,
    require_ready,
    reserved,
    revision_estimate,
)
from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import ArtifactLimitError, InvalidOptionsError
from app.modules.notebooks.domain.prompts.slides_revise import MAX_INSTRUCTION_CHARS
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

MAX_CHANGES: Final = 10


def _invalid(detail: str) -> InvalidOptionsError:
    return InvalidOptionsError(
        params={"details": [detail]}, support_details=detail[:200]
    )


def clean_changes(
    changes: list[dict[str, Any]], slide_ids: set[str]
) -> list[dict[str, str]]:
    """Check `[{slide_id, instruction}]` against the deck and normalise it.

    Raises:
        InvalidOptionsError: Not 1 to 10 changes, an unknown or repeated slide id, or
            an instruction that is empty or over 500 characters.
    """
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise _invalid(f"changes: 1 to {MAX_CHANGES} changes")
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for change in changes:
        slide_id = str(change.get("slide_id") or "").strip()
        instruction = str(change.get("instruction") or "").strip()
        if slide_id not in slide_ids or slide_id in seen:
            raise _invalid("changes: the slide does not exist or is named twice")
        if not 1 <= len(instruction) <= MAX_INSTRUCTION_CHARS:
            raise _invalid(f"instruction: 1 to {MAX_INSTRUCTION_CHARS} characters")
        seen.add(slide_id)
        cleaned.append({"slide_id": slide_id, "instruction": instruction})
    return cleaned


class ReviseSlides:
    """Queues a new deck in which only the named slides are rewritten."""

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
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        changes: list[dict[str, Any]],
    ) -> Artifact:
        """Create the revision (`parent_id` = the deck) and start its job.

        It is one more slides request for the quotas, but cheap: the model sees only
        the deck and the changes, not the sources.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The output is not a deck, or the changes are wrong.
            ArtifactNotReadyError: The deck is not ready.
            ArtifactLimitError: The notebook already holds the maximum of outputs.
            LimitReachedError: The weighted-token budget is used up.
            QuotaExceededError: The daily count of slides is used up.
            BusyError: Too many outputs are generating already.
        """
        user_id = actor.user_id
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, user_id, notebook_id, for_update=True)
            parent = await load_artifact(uow, user_id, notebook_id, artifact_id)
            content = require_ready(parent, ArtifactKind.SLIDES)
            slides = content.get("slides") or []
            cleaned = clean_changes(changes, {str(s.get("id")) for s in slides})
            limit = self.settings.notebooks.max_artifacts
            if await uow.artifacts.count_live(notebook.id) >= limit:
                raise ArtifactLimitError(params={"limit": limit})
            course = notebook.is_course_workspace
            await self.budget.pool(course).require(
                user_id, revision_estimate(content_bytes([slides, cleaned]))
            )
            revision = queued_artifact(
                notebook=notebook,
                kind=ArtifactKind.SLIDES,
                title=parent.title,
                options={**parent.options, REVISE_KEY: {"changes": cleaned}},
                prompt=parent.prompt,
                source_ids=list(parent.source_ids),
                source_map=dict(parent.source_map),
                now=self.clock.now(),
                parent_id=parent.id,
            )
            if course:  # a shared notebook: the staff member who asked pays
                revision.requested_by = user_id
            quota = self.quota.pool(course)
            async with reserved(quota, user_id, ArtifactKind.SLIDES, revision.id):
                await uow.artifacts.add(revision)
                kick_generation(uow, self.kicker, revision.id)
                await uow.commit()
        return revision
