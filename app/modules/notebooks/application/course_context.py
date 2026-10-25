"""The course a workspace belongs to, as context of its chat and Studio prompts."""

from uuid import UUID

from app.modules.notebooks.domain.context import CourseContext
from app.modules.notebooks.domain.course_outline import (
    DESCRIPTION_MAX_CHARS,
    STEP_TEXT_MAX_CHARS,
    cut,
    outline_text,
)
from app.modules.notebooks.domain.entities import Notebook
from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.lms import LmsWorkspace

import structlog

log = structlog.get_logger(__name__)


def step_id_of(options: dict[str, object]) -> UUID | None:
    """The `step_id` of a Studio request's options, if it names a valid one."""
    raw = options.get("step_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


class CourseContextLoader:
    """Reads the draft outline (and one step's draft) of a workspace's course.

    The context is never a source: it cannot be cited. Notebooks that are not course
    workspaces, and processes without the LMS, get None.
    """

    def __init__(self, workspace: LmsWorkspace | None) -> None:
        """Store the LMS side of the workspaces (None: no LMS in this process)."""
        self.workspace = workspace

    async def load(
        self, notebook: Notebook, *, step_id: UUID | None = None
    ) -> CourseContext | None:
        """Return the course context of a workspace, or None.

        Args:
            notebook: The notebook of the request.
            step_id: A step whose current draft the model should see (a lesson that
                is written for it); a step of another course is ignored.
        """
        if (
            self.workspace is None
            or not notebook.is_course_workspace
            or notebook.course_id is None
        ):
            return None
        brief = await self.workspace.course_brief(notebook.course_id)
        if brief is None:
            return None
        step_title, step_text = await self._step(notebook.course_id, step_id)
        return CourseContext(
            title=" ".join(brief.title.split()),
            description=cut(brief.description.strip(), DESCRIPTION_MAX_CHARS),
            outline=outline_text(brief),
            step_title=step_title,
            step_text=step_text,
        )

    async def _step(
        self, course_id: UUID, step_id: UUID | None
    ) -> tuple[str | None, str | None]:
        """The title and the draft text of a step of the course (None, None if not)."""
        if step_id is None or self.workspace is None:
            return None, None
        try:
            step = await self.workspace.draft_step_text(course_id, step_id)
        except (NotFoundError, ForbiddenError):
            log.info("notebooks_course_step_missing", step_id=str(step_id))
            return None, None
        return step.title, cut(step.text, STEP_TEXT_MAX_CHARS)
