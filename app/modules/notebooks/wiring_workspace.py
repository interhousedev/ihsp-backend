"""Course workspaces: the notebook an LMS course's staff share (LMS-AI)."""

from dataclasses import dataclass

from app.modules.notebooks.application.get_notebook_usage import GetNotebookUsage
from app.modules.notebooks.application.list_course_steps import ListCourseSteps
from app.modules.notebooks.application.open_course_workspace import (
    OpenCourseWorkspace,
)
from app.modules.notebooks.wiring_core import NotebooksCore


@dataclass(frozen=True, slots=True)
class WorkspaceServices:
    """Use cases of course workspaces (attribute = file name)."""

    open_course_workspace: OpenCourseWorkspace
    get_notebook_usage: GetNotebookUsage
    list_course_steps: ListCourseSteps


def build_workspace(core: NotebooksCore) -> WorkspaceServices:
    """Build the workspace use cases (the LMS side comes in `core.workspace`)."""
    return WorkspaceServices(
        open_course_workspace=OpenCourseWorkspace(
            uow_factory=core.uow_factory, clock=core.deps.clock
        ),
        get_notebook_usage=GetNotebookUsage(
            uow_factory=core.uow_factory, usage=core.usage
        ),
        list_course_steps=ListCourseSteps(
            uow_factory=core.uow_factory, workspace=core.workspace
        ),
    )
