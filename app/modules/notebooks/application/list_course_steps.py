"""Use case: the draft outline of a workspace's course, for the "add steps" picker."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.notebook_fields import invalid
from app.modules.notebooks.domain.errors import (
    FeatureDisabledError,
    NotebookNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.lms import CourseBrief, LmsWorkspace


@dataclass(frozen=True, slots=True)
class CourseStepsView:
    """The draft outline and the steps that are sources of the workspace already."""

    brief: CourseBrief
    added: frozenset[UUID]  # step ids whose draft is a source


def draft_key(step_id: UUID) -> str:
    """The duplicate key of a draft step source (see the LMS reader)."""
    return f"lms-draft:{step_id}"


class ListCourseSteps:
    """Reads the sections and steps of the course draft of a course workspace."""

    def __init__(
        self, *, uow_factory: UowFactory, workspace: LmsWorkspace | None
    ) -> None:
        """Store the unit of work factory and the LMS side (None: no LMS)."""
        self.uow_factory = uow_factory
        self.workspace = workspace

    async def execute(self, actor: Actor, notebook_id: UUID) -> CourseStepsView:
        """Return the outline; members who may only read see it too.

        Raises:
            NotebookNotFoundError: Not a notebook the caller may read, or the course
                is gone.
            InvalidOptionsError: The notebook is not a course workspace.
            FeatureDisabledError: This process has no LMS.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id, write=False)
            sources = await uow.sources.list_for_notebook(notebook_id)
        if not notebook.is_course_workspace or notebook.course_id is None:
            raise invalid("origin")
        if self.workspace is None:
            raise FeatureDisabledError(params={"feature": "lms"})
        brief = await self.workspace.course_brief(notebook.course_id)
        if brief is None:
            raise NotebookNotFoundError(support_details="the course is gone")
        keys = {source.ref_key for source in sources}
        added = frozenset(
            step.step_id
            for section in brief.sections
            for step in section.steps
            if draft_key(step.step_id) in keys
        )
        return CourseStepsView(brief=brief, added=added)
