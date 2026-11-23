"""The lesson tutor on Postgres: access, the course switch, no answers in the prompt."""

from app.bootstrap.adapters.lms_lesson_ai import LessonModelAdapter
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.lms.domain.learning.errors import NotEnrolledError
from app.modules.lms.domain.learning.tutor_errors import (
    TutorDailyLimitError,
    TutorDisabledError,
)
from app.modules.lms.domain.step_content import (
    CodeBlock,
    CodeTest,
    InteractiveVideoBlock,
)
from app.modules.lms.wiring_learning import LearningServices
from app.modules.lms.wiring_lesson_ai import LessonAiServices, build_lesson_ai
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.lms.learning.builders import (
    choice,
    content,
    quiz,
    seed_course,
    text_block,
    text_question,
)

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECRETS = (
    "Because option b is right",
    "Tashkent",
    "SECRET_SOLUTION_LINE",
    "HIDDEN_TEST_CODE",
    "VIDEO_RIGHT_ANSWER",
)


@pytest.fixture
def gateway() -> FakeLlmGateway:
    """The fake model; its `requests` show what the model was sent."""
    return FakeLlmGateway()


@pytest.fixture
def lesson_ai(
    deps: ModuleDeps,
    learning: LearningServices,
    gateway: FakeLlmGateway,
    settings: Settings,
) -> LessonAiServices:
    """The lesson AI wired as in production with the fake gateway."""
    return build_lesson_ai(
        deps, learning=learning, model=LessonModelAdapter(gateway, settings)
    )


def _step_with_answers() -> object:
    return content(
        "Cells",
        text_block("t", "The cell is the unit of life."),
        quiz(
            "quiz",
            [
                choice("q1", correct=["b"], explanation="Because option b is right."),
                text_question("q2", accepted=["Tashkent"]),
            ],
        ),
        CodeBlock(  # type: ignore[arg-type]
            id="code",
            instructions="Write add(a, b).",
            starter="def add(a, b):\n    pass\n",
            solution="def add(a, b):\n    return a + b  # SECRET_SOLUTION_LINE\n",
            tests=[CodeTest(id="h", code="assert HIDDEN_TEST_CODE", hidden=True)],
        ),
        InteractiveVideoBlock(  # type: ignore[arg-type]
            id="iv",
            url="https://example.org/v.mp4",
            interactions=[
                {
                    "id": "i1",
                    "at_sec": 30,
                    "text": "What next?",
                    "options": [
                        {"text": "VIDEO_RIGHT_ANSWER", "correct": True},
                        {"text": "Wrong", "correct": False},
                    ],
                }
            ],
        ),
    )


async def test_the_tutor_never_sees_answers_and_keeps_the_conversation(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    lesson_ai: LessonAiServices,
    gateway: FakeLlmGateway,
    student: Actor,
) -> None:
    """LMS-17: lesson text reaches the model; keys, solutions, hidden tests do not."""
    steps = [("s1", _step_with_answers())]
    course = await seed_course(maker, steps=steps)  # type: ignore[arg-type]
    step = course.step("s1")
    await learning.enroll_in_course.execute(student, course.id)

    first = await lesson_ai.ask_tutor.ask(
        student, step.step_id, "What is the answer to q2?", "ru"
    )

    sent = gateway.requests[-1]
    prompt = sent["system"] + repr(sent["messages"])
    assert "The cell is the unit of life." in prompt
    assert "Write add(a, b)." in prompt and "Reply in Russian." in prompt
    for secret in SECRETS:
        assert secret not in prompt
    assert sent["tuning"].task == "lms_tutor"
    assert [m.role for m in first.messages] == ["student", "tutor"]
    assert first.messages[1].text.startswith("(fake tutor)")
    assert first.remaining_today == 29

    stored = await lesson_ai.ask_tutor.conversation(student, step.step_id)
    assert [m.text for m in stored.messages] == [m.text for m in first.messages]
    assert stored.remaining_today == 29


async def test_the_course_switch_and_enrollment_gate_the_tutor(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    lesson_ai: LessonAiServices,
    student: Actor,
) -> None:
    """Not enrolled: refused; enrolled but tutor off: refused."""
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    step_id = course.step("s1").step_id
    with pytest.raises(NotEnrolledError):
        await lesson_ai.ask_tutor.ask(student, step_id, "Hi", "en")
    await learning.enroll_in_course.execute(student, course.id)
    async with maker() as session, session.begin():
        await session.execute(
            text("UPDATE lms.courses SET tutor_enabled = false WHERE id = :id"),
            {"id": course.id},
        )
    with pytest.raises(TutorDisabledError):
        await lesson_ai.ask_tutor.conversation(student, step_id)


async def test_the_daily_limit_stops_the_student(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    lesson_ai: LessonAiServices,
    settings: Settings,
    student: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quota counts per Tashkent day; 0 left raises the tutor limit error."""
    monkeypatch.setattr(settings.limits, "ai_lms_tutor_per_day_student", 1)
    course = await seed_course(maker, steps=[("s1", content("One", text_block()))])
    step_id = course.step("s1").step_id
    await learning.enroll_in_course.execute(student, course.id)
    done = await lesson_ai.ask_tutor.ask(student, step_id, "Hi", "en")
    assert done.remaining_today == 0
    with pytest.raises(TutorDailyLimitError):
        await lesson_ai.ask_tutor.ask(student, step_id, "Again", "en")
