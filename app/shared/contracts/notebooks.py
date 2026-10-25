"""Notebooks contracts (provided by notebooks; used by ai tools and composition)."""

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class NotebooksQueries(Protocol):
    """Read access to a student's notebooks for the assistant and the files module."""

    async def list_notebooks(
        self, user_id: UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return ``{id, title, emoji, source_count, last_opened_at}`` newest first."""
        ...

    async def get_notebook(
        self, user_id: UUID, notebook_id: UUID
    ) -> dict[str, Any] | None:
        """Return title, summary, key topics and the sources; None if not the user's."""
        ...

    async def search(
        self, user_id: UUID, notebook_id: UUID, query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Return passages ``{source_id, source_title, seq, page, text}`` by rank."""
        ...

    async def read_source_page(
        self, user_id: UUID, notebook_id: UUID, source_id: UUID, page: int
    ) -> dict[str, Any]:
        """Return one 8 KB page of a source's text ``{page, pages, text, ...}``."""
        ...

    async def list_artifacts(
        self, user_id: UUID, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        """Return ``{id, kind, title, status}`` of the notebook's outputs."""
        ...

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return ``(kind, notebook_id, title)`` per file, for the "used by" warning."""
        ...

    async def usage(self, user_id: UUID) -> dict[str, Any]:
        """Return the output quota counters (``{"artifacts": {"used", "limit"}}``)."""
        ...

    async def course_workspace(
        self, user_id: UUID, course_id: UUID
    ) -> dict[str, Any] | None:
        """Return ``{id, title, course_id, can_write}`` of the course's workspace.

        None when the course has no workspace yet or the user may not read it.
        """
        ...

    async def get_artifact_content(
        self, user_id: UUID, notebook_id: UUID, artifact_id: UUID
    ) -> dict[str, Any] | None:
        """Return ``{id, kind, title, status, content}`` of a ready output.

        None when the output does not exist, is not ready or is not the user's to read.
        """
        ...

    async def shared_artifact(self, artifact_id: UUID) -> dict[str, Any] | None:
        """Return ``{id, owner_id, kind, title, options, content}`` of a ready output.

        For public shares: no access check. None when it is missing, deleted or not
        ready.
        """
        ...


class NotebooksCommands(Protocol):
    """Writes the assistant may perform for a student after an approval."""

    async def create_notebook(
        self, actor: Actor, title: str, sources: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a notebook with sources ``{kind: "file", file_id}`` or text."""
        ...

    async def add_sources(
        self, actor: Actor, notebook_id: UUID, sources: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add sources to the student's notebook; return the created items."""
        ...

    async def request_artifact(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: str,
        options: dict[str, Any],
        prompt: str | None,
    ) -> dict[str, Any]:
        """Queue a Studio output; return ``{id, kind, status}``."""
        ...

    async def open_course_workspace(
        self, actor: Actor, course_id: UUID
    ) -> dict[str, Any]:
        """Get or create the workspace notebook of a course (needs ``edit``).

        Returns ``{id, title, course_id, can_write}``.
        """
        ...

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

        A ``course_plan`` creates the sections and steps the draft does not have; a
        ``lesson_draft`` fills ``target_step_id`` (``replace``) or, without a step id,
        creates a new step in ``target_section_id``; a ``quiz`` or ``flashcards``
        output is appended to ``target_step_id`` as a test or flash cards block.
        Returns ``{"kind", "created_sections", "created_steps", "step_id",
        "lock_version", "draft_seq"}`` (the ``ApplyResult`` of the HTTP API).

        Raises:
            NotFoundError: The workspace or the output is not the actor's to use.
            ValidationFailedError: The output cannot be applied to that target.
        """
        ...
