"""Builders of step content and of published courses for the learning tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.step_content import (
    AnswerConfig,
    Card,
    FlashcardsBlock,
    Option,
    Question,
    StepContent,
    TestBlock,
    TestConfig,
    TextBlock,
    canonical_hash,
)
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.infrastructure.orm.course_staff import CourseStaff
from app.modules.lms.infrastructure.orm.course_step import CourseStep
from app.modules.lms.infrastructure.orm.course_version import CourseVersion
from app.modules.lms.infrastructure.orm.step_revision import StepRevision
from app.shared.ids import new_id

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECTION_ID = "sec-1"
PUBLISHED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


# - - - Content - - -


def choice(
    question_id: str,
    *,
    correct: Sequence[str],
    options: Sequence[str] = ("a", "b", "c"),
    multiple: bool = False,
    points: float = 1.0,
    pinned: Sequence[str] = (),
    explanation: str | None = "Because.",
) -> Question:
    """A single or multiple choice question; option ids are `<question>-<letter>`."""
    return Question(
        id=question_id,
        type="multiple" if multiple else "single",
        prompt=f"Question {question_id}?",
        points=points,
        explanation=explanation,
        options=[
            Option(
                id=f"{question_id}-{letter}",
                text=f"Option {letter}",
                correct=letter in correct,
                pinned=letter in pinned,
            )
            for letter in options
        ],
    )


def text_question(
    question_id: str,
    *,
    accepted: Sequence[str] = (),
    regex: str | None = None,
    case_sensitive: bool = False,
    points: float = 1.0,
) -> Question:
    """A text question."""
    return Question(
        id=question_id,
        type="text",
        prompt=f"Question {question_id}?",
        points=points,
        explanation="Text explanation.",
        answer=AnswerConfig(
            accepted=list(accepted) or None, regex=regex, case_sensitive=case_sensitive
        ),
    )


def number_question(
    question_id: str, *, value: float, tolerance: float = 0.0, points: float = 1.0
) -> Question:
    """A number question."""
    return Question(
        id=question_id,
        type="number",
        prompt=f"Question {question_id}?",
        points=points,
        explanation="Number explanation.",
        answer=AnswerConfig(value=value, tolerance=tolerance),
    )


def quiz(
    block_id: str = "quiz",
    questions: Sequence[Question] | None = None,
    **config: Any,
) -> TestBlock:
    """A test block; keyword arguments are TestConfig fields."""
    return TestBlock(
        id=block_id,
        config=TestConfig(**config),
        questions=list(questions or [choice("q1", correct=["a"])]),
    )


def text_block(block_id: str = "text", markdown: str = "Read this.") -> TextBlock:
    """A markdown block."""
    return TextBlock(id=block_id, markdown=markdown)


def cards(block_id: str = "cards", count: int = 3) -> FlashcardsBlock:
    """A flash card block with cards `c1`..`cN`."""
    return FlashcardsBlock(
        id=block_id,
        cards=[
            Card(id=f"c{i}", front=f"Front {i}", back=f"Back {i}")
            for i in range(1, count + 1)
        ],
    )


def content(
    title: str, *blocks: TextBlock | TestBlock | FlashcardsBlock
) -> StepContent:
    """Step content with the given blocks."""
    return StepContent(title=title, blocks=list(blocks))


# - - - Published courses - - -


@dataclass(slots=True)
class SeededStep:
    """A step of a seeded course with its pinned revision."""

    key: str
    step_id: UUID
    revision_id: UUID
    content: StepContent


@dataclass(slots=True)
class SeededCourse:
    """A course published by `seed_course`."""

    id: UUID
    slug: str
    created_by: UUID
    version_id: UUID | None = None
    number: int = 0
    steps: dict[str, SeededStep] = field(default_factory=dict)

    def step(self, key: str) -> SeededStep:
        """Return a step by its key."""
        return self.steps[key]


async def seed_course(
    maker: async_sessionmaker[AsyncSession],
    *,
    steps: Sequence[tuple[str, StepContent]] = (),
    slug: str = "algebra",
    title: str = "Algebra",
    visibility: str = "public",
    status: str = "active",
    invite_code: str | None = None,
    created_by: UUID | None = None,
    publish: bool = True,
) -> SeededCourse:
    """Insert a course with its steps; publish version 1 unless told otherwise."""
    creator = created_by or new_id()
    seeded = SeededCourse(id=new_id(), slug=slug, created_by=creator)
    async with maker() as session:
        session.add(
            Course(
                id=seeded.id,
                slug=slug,
                title=title,
                description=f"About {title}",
                visibility=visibility,
                invite_code=invite_code,
                status=status,
                created_by=creator,
                draft_meta={"title": title, "description": f"About {title}"},
                draft_outline={"sections": []},
                outline_hash="draft",
            )
        )
        await session.flush()
        await session.commit()
    if publish:
        await publish_version(maker, seeded, steps)
    return seeded


async def publish_version(
    maker: async_sessionmaker[AsyncSession],
    seeded: SeededCourse,
    steps: Sequence[tuple[str, StepContent]],
) -> SeededCourse:
    """Publish the next version of the course with these steps (in this order).

    A step key seen before keeps its step id and reuses its revision if the
    content is unchanged, like the authoring publish does.
    """
    async with maker() as session:
        entries = [await _pin(session, seeded, key, body) for key, body in steps]
        number = seeded.number + 1
        version = CourseVersion(
            id=new_id(),
            course_id=seeded.id,
            number=number,
            meta={"title": seeded.slug, "description": ""},
            outline={
                "sections": [
                    {
                        "id": SECTION_ID,
                        "title": "Section",
                        "steps": [
                            {
                                "step_id": str(step.step_id),
                                "revision_id": str(step.revision_id),
                                "title": step.content.title,
                            }
                            for step in entries
                        ],
                    }
                ]
            },
            changes={},
            published_by=seeded.created_by,
        )
        session.add(version)
        await session.flush()
        await session.execute(
            update(Course)
            .where(Course.id == seeded.id)
            .values(live_version_id=version.id, live_outline_hash=f"v{number}")
        )
        for step in entries:
            await session.execute(
                update(CourseStep)
                .where(CourseStep.id == step.step_id)
                .values(
                    live_revision_id=step.revision_id,
                    live_hash=canonical_hash(step.content),
                )
            )
        await session.commit()
    seeded.version_id, seeded.number = version.id, number
    seeded.steps = {step.key: step for step in entries}
    return seeded


async def _pin(
    session: AsyncSession, seeded: SeededCourse, key: str, body: StepContent
) -> SeededStep:
    """Create the step if new, and its published revision if the content is new."""
    known = seeded.steps.get(key)
    step_id = known.step_id if known else new_id()
    if known is None:
        session.add(
            CourseStep(
                id=step_id,
                course_id=seeded.id,
                draft=body.model_dump(mode="json"),
                draft_hash=canonical_hash(body),
            )
        )
        await session.flush()
    if known is not None and canonical_hash(known.content) == canonical_hash(body):
        return SeededStep(key, step_id, known.revision_id, body)
    revision_id = new_id()
    session.add(
        StepRevision(
            id=revision_id,
            step_id=step_id,
            content=body.model_dump(mode="json"),
            content_hash=canonical_hash(body),
            kind="publish",
            published_at=PUBLISHED_AT,
            created_by=seeded.created_by,
        )
    )
    await session.flush()
    return SeededStep(key, step_id, revision_id, body)


async def add_preview_revision(
    maker: async_sessionmaker[AsyncSession],
    step: SeededStep,
    body: StepContent,
    created_by: UUID,
) -> UUID:
    """Insert a `preview` revision of a step (what authoring's port would freeze)."""
    revision_id = new_id()
    async with maker() as session:
        session.add(
            StepRevision(
                id=revision_id,
                step_id=step.step_id,
                content=body.model_dump(mode="json"),
                content_hash=canonical_hash(body),
                kind="preview",
                created_by=created_by,
            )
        )
        await session.commit()
    return revision_id


async def add_staff(
    maker: async_sessionmaker[AsyncSession],
    seeded: SeededCourse,
    user_id: UUID,
    *,
    role: str = "Teacher",
    permissions: Sequence[str] = ("review",),
    show_on_page: bool = True,
    position: int = 0,
) -> None:
    """Add a course staff member."""
    async with maker() as session:
        session.add(
            CourseStaff(
                course_id=seeded.id,
                user_id=user_id,
                role=role,
                permissions=list(permissions),
                show_on_page=show_on_page,
                position=position,
                added_by=seeded.created_by,
            )
        )
        await session.commit()
