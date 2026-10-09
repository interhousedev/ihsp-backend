"""LmsSourceReader for the notebooks tests: enrolment and block kinds."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.base_error import ForbiddenError, NotFoundError
from app.shared.contracts.lms import LmsStepText
from app.shared.ids import new_id

SEPARATOR = "\n\n"


@dataclass(slots=True)
class FakeStep:
    """A step; blocks are ``(kind, text)``: ``text``, ``flashcards`` or ``test``."""

    id: UUID
    title: str
    blocks: list[tuple[str, str]] = field(default_factory=list)
    revision: int = 1


@dataclass(slots=True)
class FakeCourse:
    """A course with its steps and the enrolled users."""

    id: UUID
    title: str
    steps: dict[UUID, FakeStep] = field(default_factory=dict)
    enrolled: set[UUID] = field(default_factory=set)


class FakeLms:
    """``step_text`` exports text and flash card blocks; test blocks stay inside.

    ``calls`` lists every method the code under test used, so a test can prove that
    nothing but ``step_text`` was asked (LMS-17).
    """

    def __init__(self) -> None:
        """Start without courses."""
        self.courses: dict[UUID, FakeCourse] = {}
        self.calls: list[str] = []

    def add_course(
        self, title: str = "Biology 10", *, enrolled: tuple[UUID, ...] = ()
    ) -> FakeCourse:
        """A course with the given enrolled users."""
        course = FakeCourse(new_id(), title, enrolled=set(enrolled))
        self.courses[course.id] = course
        return course

    def add_step(
        self,
        course: FakeCourse,
        title: str = "Cells",
        blocks: tuple[tuple[str, str], ...] = (
            ("text", "A cell is the basic unit of life."),
            ("flashcards", "Q: Organelle of respiration\nA: Mitochondria"),
            ("test", "Which answer is correct? (correct: B)"),
        ),
    ) -> FakeStep:
        """A step with its blocks."""
        step = FakeStep(new_id(), title, list(blocks))
        course.steps[step.id] = step
        return step

    async def my_courses(self, user_id: UUID) -> list[dict[str, Any]]:
        """The courses the user is enrolled in."""
        self.calls.append("my_courses")
        return [
            {
                "id": c.id,
                "title": c.title,
                "steps": [{"id": s.id, "title": s.title} for s in c.steps.values()],
            }
            for c in self.courses.values()
            if user_id in c.enrolled
        ]

    async def step_text(
        self, user_id: UUID, course_id: UUID, step_id: UUID
    ) -> LmsStepText:
        """Text and flash card blocks of the live revision."""
        self.calls.append("step_text")
        course = self.courses.get(course_id)
        step = course.steps.get(step_id) if course else None
        if course is None or step is None:
            raise NotFoundError()
        if user_id not in course.enrolled:
            raise ForbiddenError()
        parts = [text for kind, text in step.blocks if kind in ("text", "flashcards")]
        starts: list[int] = []
        offset = 0
        for part in parts:
            starts.append(offset)
            offset += len(part) + len(SEPARATOR)
        return LmsStepText(
            course_id=course.id,
            course_title=course.title,
            step_id=step.id,
            title=step.title,
            revision_id=f"rev-{step.revision}",
            text=SEPARATOR.join(parts),
            block_starts=tuple(starts),
        )
