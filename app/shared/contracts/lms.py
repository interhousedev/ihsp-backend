"""LMS contracts (provider: lms module; consumer: MCP)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class LmsQueries(Protocol):
    """Read access to courses for authors."""

    async def courses_for_staff(
        self, user_id: UUID, permission: str
    ) -> list[dict[str, Any]]:
        """Return courses where the user holds the permission."""
        ...

    async def course_detail(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the course outline."""
        ...

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the draft content of a step."""
        ...

    async def pending_changes(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return unpublished changes."""
        ...

    async def versions(self, course_id: UUID, actor: Actor) -> list[dict[str, Any]]:
        """Return published versions."""
        ...

    async def attempts(
        self, course_id: UUID, actor: Actor, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent attempts."""
        ...


class LmsDraftCommands(Protocol):
    """Draft edits for MCP: create, update and delete under the scopes of the token.

    Nothing here publishes. "Delete" of a course archives it; a module can be deleted
    only when empty and a step only leaves the outline, so no student data is lost.
    """

    async def create_course(
        self,
        actor: Actor,
        *,
        title: str,
        slug: str | None,
        visibility: str,
    ) -> dict[str, Any]:
        """Create a course with an empty draft (needs `lms.courses.write`)."""
        ...

    async def update_course(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        title: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        """Change the draft title and description (needs `lms.courses.write`)."""
        ...

    async def delete_course(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Archive a course (needs `lms.courses.delete`)."""
        ...

    async def update_module(
        self, actor: Actor, course_id: UUID, section_id: str, title: str
    ) -> dict[str, Any]:
        """Rename a module (section) of the draft outline."""
        ...

    async def delete_module(
        self, actor: Actor, course_id: UUID, section_id: str
    ) -> dict[str, Any]:
        """Remove an empty module from the draft outline."""
        ...

    async def update_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        title: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Rename a step and/or replace all its blocks in the draft."""
        ...

    async def delete_step(self, actor: Actor, step_id: UUID) -> dict[str, Any]:
        """Take a step out of the draft outline (its history is kept)."""
        ...

    async def create_section(
        self, actor: Actor, course_id: UUID, title: str, *, via_mcp: bool
    ) -> dict[str, Any]:
        """Add a section."""
        ...

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add a step to a section."""
        ...

    async def add_block(
        self, actor: Actor, step_id: UUID, block: dict[str, Any], *, via_mcp: bool
    ) -> dict[str, Any]:
        """Add a block to a step."""
        ...

    async def add_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add a question to a test block."""
        ...


@dataclass(frozen=True, slots=True)
class LmsStepText:
    """The text of one step of an enrolled course, for a notebook source."""

    course_id: UUID
    course_title: str
    step_id: UUID
    title: str
    revision_id: str
    text: str
    block_starts: tuple[int, ...] = ()  # offset of each block in ``text``


@dataclass(frozen=True, slots=True)
class LmsMaterialStep:
    """A step of the live version; ``revision_id`` is the version of its source."""

    step_id: UUID
    title: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class LmsMaterialVideo:
    """A video block of a live step (``file_id`` set for an upload, else ``url``)."""

    step_id: UUID
    block_id: str
    title: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class LmsCourseMaterials:
    """Everything a student's course notebook is made of, by reference.

    ``files`` are the attached files (``/files/{id}`` in the steps), ``library_items``
    the library books and materials the steps link to; both without duplicates.
    """

    course_id: UUID
    course_title: str
    steps: tuple[LmsMaterialStep, ...] = ()
    videos: tuple[LmsMaterialVideo, ...] = ()
    files: tuple[UUID, ...] = ()
    library_items: tuple[UUID, ...] = ()


class LmsSourceReader(Protocol):
    """Course steps as notebook sources (provider: lms learning; consumer: notebooks).

    Text blocks (Markdown), flash card blocks (``Front: ... / Back: ...``) and the
    questions of test blocks with their options are read; correct answers and
    explanations never are (LMS-17), those exist only in the course workspace's
    draft text (`LmsWorkspace.draft_step_text`).
    """

    async def my_courses(self, user_id: UUID) -> list[dict[str, Any]]:
        """Return the courses the user is enrolled in.

        Each item is ``{"id", "title", "steps": [{"id", "title", "section"}]}``.
        """
        ...

    async def step_text(
        self, user_id: UUID, course_id: UUID, step_id: UUID
    ) -> LmsStepText:
        """Return the live revision's text; raises ForbiddenError when not enrolled."""
        ...

    async def course_materials(
        self, user_id: UUID, course_id: UUID
    ) -> LmsCourseMaterials | None:
        """The materials of the live version; None when not enrolled or unpublished."""
        ...

    async def video_text(
        self, user_id: UUID, course_id: UUID, step_id: UUID, block_id: str
    ) -> LmsStepText:
        """The text of one video block of the live step (transcript or title).

        There is no transcript store yet, so the text is the caption (or the step
        title) and the address; it will carry the transcript when one exists.
        Raises ForbiddenError when not enrolled, NotFoundError for a missing block.
        """
        ...

    async def enrollment_pairs(self) -> list[tuple[UUID, UUID]]:
        """Every ``(course_id, user_id)`` enrollment of a published course."""
        ...


# - - - Course workspaces (an AI notebook owned by a course) - - -

COURSE_EDIT = "edit"
COURSE_VIEW_DRAFTS = "view_drafts"


@dataclass(frozen=True, slots=True)
class CourseWorkspaceAccess:
    """What a user may do in a course, as the workspace (notebook) needs to know.

    ``permissions`` are the course staff permissions in canonical order; an LMS admin
    holds all of them. ``edit`` reads and writes the workspace, ``view_drafts`` reads.
    """

    course_id: UUID
    title: str
    description: str
    permissions: tuple[str, ...]

    @property
    def can_write(self) -> bool:
        """True with the ``edit`` permission."""
        return COURSE_EDIT in self.permissions

    @property
    def can_read(self) -> bool:
        """True with ``edit`` or ``view_drafts``."""
        return self.can_write or COURSE_VIEW_DRAFTS in self.permissions


@dataclass(frozen=True, slots=True)
class CourseStepBrief:
    """One step of the draft outline."""

    step_id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class CourseSectionBrief:
    """One section of the draft outline."""

    section_id: str
    title: str
    steps: tuple[CourseStepBrief, ...] = ()


@dataclass(frozen=True, slots=True)
class CourseBrief:
    """The draft outline of a course, for prompts and for the workspace."""

    course_id: UUID
    title: str
    description: str
    draft_seq: int
    sections: tuple[CourseSectionBrief, ...] = ()


class LmsWorkspace(Protocol):
    """Staff side of a course workspace (provider: lms authoring).

    Consumers: notebooks (who may open the workspace, the draft text of a step as a
    source, the outline as context of a Studio output) and ai (the author assistant).
    """

    async def course_access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Return the user's access to the course, or None for a stranger.

        Course staff and LMS admins count; students enrolled in the course do not.
        Unknown courses and strangers look the same (None).
        """
        ...

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """Return the draft outline of the course; None when it does not exist.

        No access check: the caller has just checked ``course_access``.
        """
        ...

    async def draft_step_text(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        """Return the text of a step's *draft* (text and flash card blocks, no tests).

        ``revision_id`` is the draft hash, so a changed draft marks a source as
        outdated. No access check (the caller checked when the source was added).

        Raises:
            NotFoundError: The step does not belong to the course.
        """
        ...


class LmsWorkspaceCommands(Protocol):
    """The authoring writes of the workspace that go beyond add-only MCP edits.

    Kept apart from ``LmsDraftCommands`` on purpose: MCP-6 clients can only append.
    Both methods check ``edit`` on the course through the LMS use cases.
    """

    async def apply_outline(
        self,
        actor: Actor,
        course_id: UUID,
        sections: Sequence[dict[str, Any]],
        *,
        dry_run: bool = False,
        add_briefs: bool = False,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Create the sections and steps of a plan that the draft does not have yet.

        ``sections`` is ``[{"title", "steps": [{"title", "brief"?}]}]``. A section whose
        title (compared without case and extra spaces) exists is reused, and so is a
        step with the same title inside it; nothing is ever renamed, moved or removed.
        One transaction under the course lock; ``dry_run`` only reports. With
        ``add_briefs`` a *new* step gets its ``brief`` (Markdown) as a first text block.

        Returns ``{"created_sections": [{"id", "title"}], "created_steps": [{"step_id",
        "section_id", "title"}], "existing_sections": int, "existing_steps": int,
        "plan": [{"title", "section_id", "action", "steps": [{"title", "step_id",
        "action"}]}], "draft_seq": int}`` where ``action`` is ``new`` or ``exists``.
        """
        ...

    async def replace_step(
        self,
        actor: Actor,
        step_id: UUID,
        content: dict[str, Any],
        lock_version: int,
        *,
        via_ai: bool = True,
    ) -> dict[str, Any]:
        """Replace the draft content of a step (``{"title", "blocks"}``).

        Ids may be empty strings (the server assigns them). A stale ``lock_version``
        raises ``DraftConflictError``; invalid content raises ``ContentInvalidError``.
        Returns ``{"step_id", "blocks", "lock_version"}``.
        """
        ...
