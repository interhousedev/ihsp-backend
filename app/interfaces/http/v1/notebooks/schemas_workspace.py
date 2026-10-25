"""Request and response models of course workspaces (LMS-AI § 4)."""

from typing import Self
from uuid import UUID

from app.modules.notebooks.application.list_course_steps import CourseStepsView
from app.modules.notebooks.application.open_course_workspace import OpenedWorkspace

from pydantic import BaseModel


class OpenCourseWorkspaceBody(BaseModel):
    """POST /v1/notebooks/course-workspaces."""

    course_id: UUID


class CourseWorkspaceResponse(BaseModel):
    """The workspace of a course and what the caller may do in it."""

    notebook_id: UUID
    course_id: UUID
    title: str
    can_write: bool
    created: bool  # True when this request created it

    @classmethod
    def from_view(cls, opened: OpenedWorkspace, course_id: UUID) -> Self:
        """Build from the opened workspace."""
        return cls(
            notebook_id=opened.notebook.id,
            course_id=course_id,
            title=opened.notebook.title,
            can_write=opened.can_write,
            created=opened.created,
        )


class CourseStepItemResponse(BaseModel):
    """One step of the draft outline; `added` when its draft is a source already."""

    id: UUID
    title: str
    added: bool


class CourseSectionItemResponse(BaseModel):
    """One section of the draft outline."""

    id: str
    title: str
    steps: list[CourseStepItemResponse]


class CourseStepsResponse(BaseModel):
    """GET /v1/notebooks/{id}/course-steps: the draft outline for the step picker."""

    course_id: UUID
    title: str
    sections: list[CourseSectionItemResponse]

    @classmethod
    def from_view(cls, view: CourseStepsView) -> Self:
        """Build from the outline and the steps that are sources already."""
        brief = view.brief
        return cls(
            course_id=brief.course_id,
            title=brief.title,
            sections=[
                CourseSectionItemResponse(
                    id=section.section_id,
                    title=section.title,
                    steps=[
                        CourseStepItemResponse(
                            id=step.step_id,
                            title=step.title,
                            added=step.step_id in view.added,
                        )
                        for step in section.steps
                    ],
                )
                for section in brief.sections
            ],
        )
