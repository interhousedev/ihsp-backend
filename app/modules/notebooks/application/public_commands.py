"""`NotebooksCommands`: the writes the assistant makes for a student after approval.

Course staff reach their course's workspace through the same commands (the access
check of the use cases decides) and `open_course_workspace`.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from app.modules.notebooks.application.apply_views import (
    ApplyPreviewView,
    ApplyRequest,
    ApplyResultView,
)
from app.modules.notebooks.application.open_course_workspace import OpenedWorkspace
from app.modules.notebooks.application.views import AddSourcesResult
from app.modules.notebooks.domain.entities import Artifact, Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    FeatureDisabledError,
    InvalidOptionsError,
)
from app.modules.notebooks.domain.source_input import SourceInput
from app.shared.actor import Actor

from pydantic import TypeAdapter, ValidationError

_SOURCE_INPUT: TypeAdapter[SourceInput] = TypeAdapter(SourceInput)


class CreateNotebookUseCase(Protocol):
    """What `NotebooksCommandsImpl` needs of `CreateNotebook`."""

    async def execute(
        self, actor: Actor, title: str | None = None, emoji: str | None = None
    ) -> Notebook:
        """Store a new notebook."""
        ...


class AddSourcesUseCase(Protocol):
    """What `NotebooksCommandsImpl` needs of `AddSources`."""

    async def execute(
        self, actor: Actor, notebook_id: UUID, items: Sequence[SourceInput]
    ) -> AddSourcesResult:
        """Add the sources; refused ones are reported, not raised."""
        ...


class RequestArtifactUseCase(Protocol):
    """What `NotebooksCommandsImpl` needs of `RequestArtifact`."""

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: ArtifactKind,
        options: Mapping[str, Any],
        prompt: str | None,
    ) -> Artifact:
        """Queue a Studio output."""
        ...


class OpenCourseWorkspaceUseCase(Protocol):
    """What `NotebooksCommandsImpl` needs of `OpenCourseWorkspace`."""

    async def execute(self, actor: Actor, course_id: UUID) -> OpenedWorkspace:
        """Get or create the workspace of the course."""
        ...


class ApplyArtifactUseCase(Protocol):
    """What `NotebooksCommandsImpl` needs of `ApplyCourseArtifact`."""

    async def apply(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        request: ApplyRequest,
    ) -> ApplyResultView:
        """Write a ready course output into the course draft."""
        ...

    async def preview(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        request: ApplyRequest,
    ) -> ApplyPreviewView:
        """Say what `apply` would do."""
        ...


def parse_inputs(sources: Sequence[Mapping[str, Any]]) -> list[SourceInput]:
    """Validate source dicts with the `SourceInput` union (unknown kinds fail)."""
    parsed: list[SourceInput] = []
    for index, raw in enumerate(sources):
        try:
            parsed.append(_SOURCE_INPUT.validate_python(raw))
        except ValidationError as exc:
            raise InvalidOptionsError(
                params={"field": f"sources.{index}"},
                support_details=f"source {index}: {exc.errors()[0]['msg']}",
            ) from exc
    return parsed


def _created(source: Source) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "kind": source.kind.value,
        "title": source.title,
        "status": source.status.value,
    }


class NotebooksCommandsImpl:
    """Implements `app.shared.contracts.notebooks.NotebooksCommands`."""

    def __init__(
        self,
        *,
        create_notebook: CreateNotebookUseCase,
        add_sources: AddSourcesUseCase,
        request_artifact: RequestArtifactUseCase,
        apply_artifact: ApplyArtifactUseCase | None = None,
        open_course_workspace: OpenCourseWorkspaceUseCase | None = None,
    ) -> None:
        """Store the use cases the commands go through."""
        self.create_notebook_case = create_notebook
        self.add_sources_case = add_sources
        self.request_artifact_case = request_artifact
        self.apply_artifact_case = apply_artifact
        self.open_course_workspace_case = open_course_workspace

    async def create_notebook(
        self, actor: Actor, title: str, sources: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a notebook, then add the sources; return what was added or refused.

        The sources are validated before anything is stored. An empty title gives
        the default "Untitled notebook".
        """
        items = parse_inputs(sources)
        notebook = await self.create_notebook_case.execute(
            actor, title.strip() or None, None
        )
        added = AddSourcesResult()
        if items:
            added = await self.add_sources_case.execute(actor, notebook.id, items)
        return {
            "id": str(notebook.id),
            "title": notebook.title,
            "added": len(added.items),
            "rejected": [
                {"index": r.index, "type": r.error.code} for r in added.rejected
            ],
        }

    async def add_sources(
        self, actor: Actor, notebook_id: UUID, sources: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add sources to the student's notebook; return the created items.

        When every item is refused the first refusal is raised, so the assistant
        learns why.
        """
        items = parse_inputs(sources)
        result = await self.add_sources_case.execute(actor, notebook_id, items)
        if not result.items and result.rejected:
            raise result.rejected[0].error
        return [_created(source) for source in result.items]

    async def request_artifact(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: str,
        options: dict[str, Any],
        prompt: str | None,
    ) -> dict[str, Any]:
        """Queue a Studio output; return ``{id, kind, status}``."""
        try:
            artifact_kind = ArtifactKind(kind)
        except ValueError as exc:
            raise InvalidOptionsError(
                params={"kind": kind}, support_details="unknown kind"
            ) from exc
        artifact = await self.request_artifact_case.execute(
            actor, notebook_id, artifact_kind, options, prompt
        )
        return {
            "id": str(artifact.id),
            "kind": artifact.kind.value,
            "status": artifact.status.value,
        }

    async def apply_artifact(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        *,
        target_step_id: UUID | None = None,
        target_section_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Write a ready course output into the course draft (needs ``edit``).

        The same operation as the HTTP ``apply``; returns its ``ApplyResult``.
        """
        if self.apply_artifact_case is None:
            raise FeatureDisabledError(params={"feature": "lms"})
        result = await self.apply_artifact_case.apply(
            actor,
            notebook_id,
            artifact_id,
            ApplyRequest(
                target_step_id=target_step_id,
                target_section_id=target_section_id,
                mode=mode,
            ),
        )
        return result.as_dict()

    async def open_course_workspace(
        self, actor: Actor, course_id: UUID
    ) -> dict[str, Any]:
        """Get or create the workspace notebook of a course (needs ``edit``).

        Returns ``{id, title, course_id, can_write}``; a read-only member gets the
        existing workspace, a stranger `NotebookNotFoundError`.
        """
        if self.open_course_workspace_case is None:
            raise FeatureDisabledError(params={"feature": "lms"})
        opened = await self.open_course_workspace_case.execute(actor, course_id)
        return {
            "id": str(opened.notebook.id),
            "title": opened.notebook.title,
            "course_id": str(course_id),
            "can_write": opened.can_write,
        }
