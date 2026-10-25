"""In-memory `LmsWorkspace` for the notebooks tests: staff permissions and drafts."""

import hashlib
from dataclasses import dataclass, field
from uuid import UUID

from app.shared.base_error import NotFoundError
from app.shared.contracts.lms import (
    COURSE_EDIT,
    COURSE_VIEW_DRAFTS,
    CourseBrief,
    CourseSectionBrief,
    CourseStepBrief,
    CourseWorkspaceAccess,
    LmsStepText,
)
from app.shared.ids import new_id

SEPARATOR = "\n\n"
EDIT: tuple[str, ...] = (COURSE_EDIT,)
VIEW: tuple[str, ...] = (COURSE_VIEW_DRAFTS,)
REVIEW: tuple[str, ...] = ("review",)  # a permission that does not open the workspace


@dataclass(slots=True)
class DraftStep:
    """A draft step; blocks are ``(kind, text)``: ``text``, ``flashcards``, ``test``."""

    id: UUID
    title: str
    blocks: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class DraftSection:
    """A section of the draft outline."""

    id: str
    title: str
    steps: list[DraftStep] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceCourse:
    """A course with its staff (user -> permissions) and its draft outline."""

    id: UUID
    title: str
    description: str = ""
    staff: dict[UUID, tuple[str, ...]] = field(default_factory=dict)
    sections: list[DraftSection] = field(default_factory=list)
    draft_seq: int = 1


class FakeLmsWorkspace:
    """Implements `LmsWorkspace`; tests change permissions and drafts directly."""

    def __init__(self) -> None:
        """Start without courses; `calls` lists the methods used."""
        self.courses: dict[UUID, WorkspaceCourse] = {}
        self.calls: list[str] = []

    # - - - arranging - - -

    def add_course(
        self, title: str = "Physics 9", description: str = "Mechanics basics"
    ) -> WorkspaceCourse:
        """A course without staff and without sections."""
        course = WorkspaceCourse(new_id(), title, description)
        self.courses[course.id] = course
        return course

    def grant(
        self, course: WorkspaceCourse, user_id: UUID, permissions: tuple[str, ...]
    ) -> None:
        """Give a user course permissions (an empty tuple removes them)."""
        if permissions:
            course.staff[user_id] = permissions
        else:
            course.staff.pop(user_id, None)

    def add_step(
        self,
        course: WorkspaceCourse,
        title: str = "Newton's laws",
        *,
        section: str = "Dynamics",
        blocks: tuple[tuple[str, str], ...] = (
            ("text", "A force changes the motion of a body. F = m a."),
            ("flashcards", "Q: Unit of force\nA: Newton"),
            ("test", "Which law? (correct: second)"),
        ),
    ) -> DraftStep:
        """A draft step in the named section (created when missing)."""
        found = next((s for s in course.sections if s.title == section), None)
        if found is None:
            found = DraftSection(f"s{len(course.sections) + 1}", section)
            course.sections.append(found)
        step = DraftStep(new_id(), title, list(blocks))
        found.steps.append(step)
        return step

    def edit_step(self, step: DraftStep, text: str) -> None:
        """Replace the first text block of a draft (its hash changes)."""
        step.blocks = [("text", text), *step.blocks[1:]]

    # - - - LmsWorkspace - - -

    async def course_access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """The user's permissions, or None for a stranger or an unknown course."""
        self.calls.append("course_access")
        course = self.courses.get(course_id)
        if course is None or user_id not in course.staff:
            return None
        return CourseWorkspaceAccess(
            course_id=course.id,
            title=course.title,
            description=course.description,
            permissions=course.staff[user_id],
        )

    async def course_brief(self, course_id: UUID) -> CourseBrief | None:
        """The draft outline."""
        self.calls.append("course_brief")
        course = self.courses.get(course_id)
        if course is None:
            return None
        return CourseBrief(
            course_id=course.id,
            title=course.title,
            description=course.description,
            draft_seq=course.draft_seq,
            sections=tuple(
                CourseSectionBrief(
                    section_id=section.id,
                    title=section.title,
                    steps=tuple(CourseStepBrief(s.id, s.title) for s in section.steps),
                )
                for section in course.sections
            ),
        )

    async def draft_step_text(self, course_id: UUID, step_id: UUID) -> LmsStepText:
        """Text and flash card blocks of the draft; the hash is the version."""
        self.calls.append("draft_step_text")
        course = self.courses.get(course_id)
        step = next(
            (
                s
                for section in (course.sections if course else [])
                for s in section.steps
                if s.id == step_id
            ),
            None,
        )
        if course is None or step is None:
            raise NotFoundError()
        parts = [text for kind, text in step.blocks if kind in ("text", "flashcards")]
        starts: list[int] = []
        offset = 0
        for part in parts:
            starts.append(offset)
            offset += len(part) + len(SEPARATOR)
        text = SEPARATOR.join(parts)
        return LmsStepText(
            course_id=course.id,
            course_title=course.title,
            step_id=step.id,
            title=step.title,
            revision_id=hashlib.sha256(text.encode()).hexdigest()[:16],
            text=text,
            block_starts=tuple(starts),
        )
