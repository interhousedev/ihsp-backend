"""NB-SRC-LMS, LMS-17: course steps as notebook sources (LmsSourceReader)."""

from uuid import uuid4

from app.modules.lms.domain.learning.errors import (
    NotEnrolledError,
    StepNotFoundError,
)
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    add_staff,
    cards,
    choice,
    content,
    number_question,
    publish_version,
    quiz,
    seed_course,
    text_block,
    text_question,
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def enroll(learning: LearningServices, actor: Actor, course_id: object) -> None:
    """Enroll through the public use case."""
    await learning.enroll_in_course.execute(actor, course_id)  # type: ignore[arg-type]


async def test_a_step_is_read_as_text_blocks_and_flash_cards(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Text as Markdown, cards as Q/A, with the block offsets and revision id."""
    course = await seed_course(
        maker,
        title="Biology",
        steps=[
            (
                "s1",
                content(
                    "Cells",
                    text_block("t1", "# Cells\n\nThe cell is the unit of life."),
                    cards("c1", 2),
                    quiz(),
                    text_block("t2", "Mitochondria make ATP."),
                ),
            )
        ],
    )
    step = course.step("s1")
    await enroll(learning, student, course.id)

    result = await learning.source_reader.step_text(
        student.user_id, course.id, step.step_id
    )

    assert result.course_id == course.id and result.step_id == step.step_id
    assert result.course_title == "Biology" and result.title == "Cells"
    assert result.revision_id == str(step.revision_id)
    assert result.text == (
        "# Cells\n\nThe cell is the unit of life.\n\n"
        "Q: Front 1\nA: Back 1\n\nQ: Front 2\nA: Back 2\n\n"
        "Mitochondria make ATP."
    )
    assert len(result.block_starts) == 3
    assert [result.text[s : s + 7] for s in result.block_starts] == [
        "# Cells",
        "Q: Fron",
        "Mitocho",
    ]


async def test_test_blocks_and_their_correct_answers_never_leak(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """LMS-17: nothing of a test block reaches the text, even as a substring."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["b"], explanation="Because option b is right."),
            text_question("q2", accepted=["Tashkent"]),
            number_question("q3", value=1991),
        ],
    )
    course = await seed_course(
        maker,
        steps=[("s1", content("Quiz step", text_block("t", "Read first."), block))],
    )
    step = course.step("s1")
    await enroll(learning, student, course.id)

    result = await learning.source_reader.step_text(
        student.user_id, course.id, step.step_id
    )

    assert result.text == "Read first."
    for secret in (
        "Question q1?",
        "Option",
        "Because option b",
        "Tashkent",
        "1991",
        "q2",
    ):
        assert secret not in result.text


async def test_a_step_with_only_tests_gives_an_empty_text(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """The reader returns the step, the notebooks module decides what to do."""
    course = await seed_course(maker, steps=[("s1", content("Only test", quiz()))])
    await enroll(learning, student, course.id)

    result = await learning.source_reader.step_text(
        student.user_id, course.id, course.step("s1").step_id
    )

    assert result.text == "" and result.block_starts == ()
    assert result.title == "Only test"


async def test_a_student_who_is_not_enrolled_cannot_read_the_step(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Public courses need an enrollment first."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])

    with pytest.raises(NotEnrolledError) as caught:
        await learning.source_reader.step_text(
            student.user_id, course.id, course.step("s1").step_id
        )

    assert caught.value.status == 403


async def test_course_staff_get_no_special_access(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    teacher: Actor,
    lms_admin: Actor,
) -> None:
    """Only the enrolled student's own notebook may hold the step text."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    await add_staff(maker, course, teacher.user_id, permissions=("review", "edit"))
    step_id = course.step("s1").step_id

    for who in (teacher, lms_admin):
        with pytest.raises(NotEnrolledError):
            await learning.source_reader.step_text(who.user_id, course.id, step_id)


async def test_a_step_of_another_course_is_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """The step must belong to the course in the request."""
    algebra = await seed_course(
        maker, slug="algebra", steps=[("s1", content("A", text_block()))]
    )
    geometry = await seed_course(
        maker, slug="geometry", steps=[("s1", content("G", text_block()))]
    )
    await enroll(learning, student, algebra.id)
    await enroll(learning, student, geometry.id)

    with pytest.raises(StepNotFoundError):
        await learning.source_reader.step_text(
            student.user_id, algebra.id, geometry.step("s1").step_id
        )
    with pytest.raises(StepNotFoundError):
        await learning.source_reader.step_text(student.user_id, algebra.id, uuid4())


async def test_a_step_removed_from_the_live_version_is_not_found(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Steps that are not in the live outline do not exist for learners."""
    one, two = content("One", text_block()), content("Two", text_block())
    course = await seed_course(maker, steps=[("s1", one), ("s2", two)])
    removed = course.step("s2").step_id
    await enroll(learning, student, course.id)
    await publish_version(maker, course, [("s1", one)])

    with pytest.raises(StepNotFoundError):
        await learning.source_reader.step_text(student.user_id, course.id, removed)


async def test_the_live_revision_is_read_and_its_id_changes_with_the_content(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """A new published version gives a new revision id for 'Outdated' checks."""
    course = await seed_course(
        maker, steps=[("s1", content("Step", text_block("t", "Old text.")))]
    )
    step_id = course.step("s1").step_id
    await enroll(learning, student, course.id)
    before = await learning.source_reader.step_text(student.user_id, course.id, step_id)

    await publish_version(
        maker, course, [("s1", content("Step", text_block("t", "New text.")))]
    )
    after = await learning.source_reader.step_text(student.user_id, course.id, step_id)

    assert (before.text, after.text) == ("Old text.", "New text.")
    assert before.revision_id != after.revision_id
    assert after.revision_id == str(course.step("s1").revision_id)


async def test_my_courses_lists_enrolled_courses_with_their_live_steps(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    other_student: Actor,
) -> None:
    """Courses by title, steps in outline order, with the section title."""
    biology = await seed_course(
        maker,
        slug="biology",
        title="Biology",
        steps=[
            ("a", content("Cells", text_block())),
            ("b", content("Genes", text_block())),
        ],
    )
    algebra = await seed_course(
        maker, slug="algebra", title="Algebra", steps=[("c", content("Sets", cards()))]
    )
    await seed_course(
        maker, slug="art", title="Art", steps=[("d", content("Line", text_block()))]
    )
    await enroll(learning, student, biology.id)
    await enroll(learning, student, algebra.id)

    mine = await learning.source_reader.my_courses(student.user_id)
    theirs = await learning.source_reader.my_courses(other_student.user_id)

    assert [c["title"] for c in mine] == ["Algebra", "Biology"]
    assert mine[1]["id"] == biology.id
    assert mine[1]["steps"] == [
        {"id": biology.step("a").step_id, "title": "Cells", "section": "Section"},
        {"id": biology.step("b").step_id, "title": "Genes", "section": "Section"},
    ]
    assert theirs == []


async def test_my_courses_skips_a_course_without_a_live_version(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    """Nothing to read in an unpublished course."""
    draft = await seed_course(maker, slug="draft", publish=False)
    async with maker() as session:
        session.add(Enrollment(course_id=draft.id, user_id=student.user_id, via="self"))
        await session.commit()

    assert await learning.source_reader.my_courses(student.user_id) == []
