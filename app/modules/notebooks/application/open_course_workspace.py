"""Use case: open (get or create) the workspace notebook of an LMS course (LMS-AI)."""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.limits import NOTEBOOK_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.lms import CourseWorkspaceAccess
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

WORKSPACE_EMOJI: Final = "🎓"
FALLBACK_TITLE: Final = "Course"


@dataclass(frozen=True, slots=True)
class OpenedWorkspace:
    """The workspace, whether this call created it, and what the caller may do."""

    notebook: Notebook
    created: bool

    @property
    def can_write(self) -> bool:
        """True for a course member with ``edit``."""
        return self.notebook.can_write


def workspace_title(course_title: str) -> str:
    """The course title on one line, cut to the notebook title limit."""
    flat = " ".join(course_title.split())[:NOTEBOOK_TITLE_MAX_CHARS].strip()
    return flat or FALLBACK_TITLE


async def _course_access(
    uow: NotebooksUnitOfWork, user_id: UUID, course_id: UUID
) -> CourseWorkspaceAccess:
    """The caller's access to the course; a stranger gets the 404 of a notebook."""
    access = await uow.course_gate.access(user_id, course_id)
    if access is None or not access.can_read:
        raise NotebookNotFoundError()
    return access


class OpenCourseWorkspace:
    """Returns a course's workspace; the first editor who opens it creates it.

    The creator becomes the workspace owner (every row of the workspace carries that
    id), but the workspace belongs to the course: any member with ``edit`` writes in
    it, a member with ``view_drafts`` only reads it.
    """

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def find(self, user_id: UUID, course_id: UUID) -> Notebook | None:
        """Return the course's workspace if it exists and the user may read it.

        Raises:
            NotebookNotFoundError: The user is not a member of the course staff.
        """
        async with self.uow_factory() as uow:
            access = await _course_access(uow, user_id, course_id)
            found = await uow.notebooks.get_by_course(course_id)
        if found is not None:
            found.can_write = access.can_write
        return found

    async def execute(self, actor: Actor, course_id: UUID) -> OpenedWorkspace:
        """Get the workspace, or create it for a member with ``edit``.

        Opening counts as opening the notebook (`last_opened_at`). Two editors who
        open a new course at once get the same workspace (the unique index decides,
        the loser reads the winner's).

        Raises:
            NotebookNotFoundError: A stranger, or a read-only member of a course that
                has no workspace yet.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            access = await _course_access(uow, actor.user_id, course_id)
            found = await uow.notebooks.get_by_course(course_id)
            created = False
            if found is None:
                if not access.can_write:
                    raise NotebookNotFoundError()
                found, created = await self._create(uow, actor, access)
            found.last_opened_at = now
            await uow.notebooks.save(found)
            await uow.commit()
            stored = await uow.notebooks.get(found.id)
        notebook = stored or found
        notebook.can_write = access.can_write
        if created:
            log.info("notebooks_workspace_created", course_id=str(course_id))
        return OpenedWorkspace(notebook=notebook, created=created)

    async def _create(
        self, uow: NotebooksUnitOfWork, actor: Actor, access: CourseWorkspaceAccess
    ) -> tuple[Notebook, bool]:
        """Insert the workspace; on a lost race return the one that won (False)."""
        now = self.clock.now()
        notebook = Notebook(
            id=new_id(),
            owner_id=actor.user_id,
            title=workspace_title(access.title),
            title_auto=False,
            emoji=WORKSPACE_EMOJI,
            emoji_auto=False,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
            origin=NotebookOrigin.COURSE,
            course_id=access.course_id,
        )
        if await uow.notebooks.add_workspace(notebook):
            return notebook, True
        winner = await uow.notebooks.get_by_course(access.course_id)
        if winner is None:  # the other request rolled back meanwhile
            raise NotebookNotFoundError(support_details="workspace race lost twice")
        return winner, False
