"""Exam block sittings over the real database: timing, answer hiding, results."""

from datetime import timedelta
from typing import Any

from app.modules.lms.application.learning.views import LearningExamBlockView
from app.modules.lms.domain.learning.errors import (
    AnswerInvalidError,
    ExamModuleClosedError,
    ExamNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.step_content import ExamBlock
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import add_staff, content, seed_course

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _module(mid: str, *qids: str) -> dict[str, Any]:
    return {
        "id": mid,
        "title": mid,
        "time_limit_sec": 600,
        "questions": [
            {
                "id": q,
                "type": "single",
                "prompt": f"Prompt {q}",
                "explanation": f"Because {q}",
                "options": [
                    {"id": "a", "text": "A", "correct": True},
                    {"id": "b", "text": "B"},
                ],
            }
            for q in qids
        ],
    }


def _exam() -> Any:  # noqa: ANN401
    return ExamBlock.model_validate(
        {
            "id": "sat",
            "kind": "sat",
            "scaling": {"min_score": 200, "max_score": 800},
            "sections": [
                {
                    "id": "rw",
                    "title": "Reading and Writing",
                    "adaptive": True,
                    "modules": [
                        _module("m1", "q1", "q2"),
                        _module("hard", "q3", "q4"),
                        _module("easy", "q5", "q6"),
                    ],
                },
                {"id": "math", "title": "Math", "modules": [_module("m3", "q7")]},
            ],
        }
    )


async def test_exam_lifecycle_deadline_and_answer_hiding(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    clock: FixedClock,
) -> None:
    course = await seed_course(maker, steps=[("s", content("SAT", _exam()))])
    step_id = course.step("s").step_id
    with pytest.raises(NotEnrolledError):
        await learning.exam_start.execute(student, step_id, "sat")
    await learning.enroll_in_course.execute(student, course.id)
    with pytest.raises(ExamNotFoundError):
        await learning.exam_get.execute(student, step_id, "nope")

    fresh = await learning.exam_get.execute(student, step_id, "sat")
    assert fresh.status == "not_started" and fresh.current is None
    assert fresh.next is not None and fresh.next.module_id == "m1"

    started = await learning.exam_start.execute(student, step_id, "sat")
    current = started.current
    assert started.status == "in_module" and current is not None
    assert current.deadline_at == clock.now() + timedelta(seconds=600)
    dumped = str(started.model_dump())
    assert "q3" not in dumped and "Because" not in dumped and "correct" not in dumped
    again = await learning.exam_start.execute(student, step_id, "sat")
    assert again.current is not None and again.current.started_at == current.started_at

    with pytest.raises(AnswerInvalidError):
        await learning.exam_answers.execute(
            student, step_id, "sat", "m1", {"q3": {"option_ids": ["a"]}}
        )
    await learning.exam_answers.execute(
        student, step_id, "sat", "m1", {"q1": {"option_ids": ["a"]}}
    )
    clock.advance(seconds=600 + 20)  # within the grace
    await learning.exam_answers.execute(
        student, step_id, "sat", "m1", {"q2": {"option_ids": ["a"]}}
    )
    clock.advance(seconds=20)  # grace over: the module closes as late
    with pytest.raises(ExamModuleClosedError):
        await learning.exam_answers.execute(
            student, step_id, "sat", "m1", {"q2": {"option_ids": ["b"]}}
        )
    between = await learning.exam_get.execute(student, step_id, "sat")
    assert between.status == "between" and between.modules_done == 1
    assert between.next is not None and between.next.module_id == "hard"
    assert between.next.module_no == 2 and not between.next_is_new_section

    second = await learning.exam_start.execute(student, step_id, "sat")
    assert second.current is not None and second.current.module_id == "hard"
    await learning.exam_answers.execute(
        student, step_id, "sat", "hard", {"q3": {"option_ids": ["a"]}}
    )
    after = await learning.exam_submit.execute(student, step_id, "sat", "hard")
    assert after.next is not None and after.next_is_new_section

    await learning.exam_start.execute(student, step_id, "sat")
    done = await learning.exam_submit.execute(student, step_id, "sat", "m3")
    result = done.result
    assert done.status == "finished" and result is not None
    assert [m.module_id for m in result.modules] == ["m1", "hard", "m3"]
    assert result.modules[0].late and result.modules[0].score == 2
    assert result.sections[0].scaled_score == 650  # 3 of 4 points: 200 + 600 * 0.75
    assert result.sections[1].scaled_score == 200
    assert result.scaled_total == 850
    assert result.modules[0].review[0].explanation == "Because q1"

    view = await learning.get_step_view.execute(student, course.id, step_id)
    block = next(b for b in view.blocks if b.id == "sat")
    assert isinstance(block, LearningExamBlockView) and block.passed
    assert view.completed and view.points_total == 5 and view.points_earned == 3
    with pytest.raises(ExamModuleClosedError):
        await learning.exam_answers.execute(
            student, step_id, "sat", "m3", {"q7": {"option_ids": ["a"]}}
        )


async def test_staff_preview_sitting_is_unscored(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    course = await seed_course(maker, steps=[("s", content("SAT", _exam()))])
    step_id = course.step("s").step_id
    await add_staff(maker, course, student.user_id)

    for module_id in ("m1", "easy", "m3"):
        started = await learning.exam_start.execute(student, step_id, "sat")
        assert started.current is not None and started.current.module_id == module_id
        done = await learning.exam_submit.execute(student, step_id, "sat", module_id)
    assert done.status == "finished" and done.result is not None

    await learning.enroll_in_course.execute(student, course.id)
    view = await learning.get_step_view.execute(student, course.id, step_id)
    block = next(b for b in view.blocks if b.id == "sat")
    assert isinstance(block, LearningExamBlockView) and block.result is None
    assert not view.completed and view.points_earned == 0
    real = await learning.exam_get.execute(student, step_id, "sat")
    assert real.status == "not_started"
