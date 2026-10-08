"""Reusable steps of the learning tests: an enrolled student and a quiz to take."""

from typing import Any

from app.modules.lms.application.learning.views import LearningAttemptResultView
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    SeededCourse,
    SeededStep,
    choice,
    content,
    number_question,
    quiz,
    seed_course,
    text_block,
    text_question,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

QUESTIONS = (
    choice("q1", correct=["a"]),
    number_question("q2", value=4),
    text_question("q3", accepted=["yes"]),
)
RIGHT: dict[str, dict[str, Any]] = {
    "q1": {"option_ids": ["q1-a"]},
    "q2": {"number": 4},
    "q3": {"text": "yes"},
}
WRONG: dict[str, dict[str, Any]] = {
    "q1": {"option_ids": ["q1-b"]},
    "q2": {"number": 5},
    "q3": {"text": "no"},
}
ONE_RIGHT: dict[str, dict[str, Any]] = {**WRONG, "q1": {"option_ids": ["q1-a"]}}


async def quiz_course(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor | None,
    *,
    with_text_step: bool = False,
    **config: Any,
) -> tuple[SeededCourse, SeededStep]:
    """Publish a course whose step `quiz` has the three-question test; enroll."""
    steps = [("quiz", content("Quiz", quiz("quiz", QUESTIONS, **config)))]
    if with_text_step:
        steps.append(("text", content("Reading", text_block())))
    seeded = await seed_course(maker, steps=steps)
    if student is not None:
        await learning.enroll_in_course.execute(student, seeded.id)
    return seeded, seeded.step("quiz")


async def take(
    learning: LearningServices,
    actor: Actor,
    step: SeededStep,
    answers: dict[str, dict[str, Any]],
    *,
    block_id: str = "quiz",
) -> LearningAttemptResultView:
    """Start an attempt, save the answers and submit it."""
    attempt = await learning.start_attempt.execute(
        actor, step.step_id, block_id, preview=False
    )
    await learning.save_answers.execute(actor, attempt.id, answers)
    return await learning.submit_attempt.execute(actor, attempt.id)
