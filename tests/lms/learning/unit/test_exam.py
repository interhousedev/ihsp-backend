"""Exam sittings: module order, adaptive routing, deadlines and scaled scores."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.modules.lms.domain.learning.exam import (
    GRACE,
    ExamSitting,
    accepts_answers,
    close_expired,
    close_run,
    exam_max_points,
    find_module,
    next_module,
    section_scores,
    start_run,
)
from app.modules.lms.domain.step_content import ExamBlock

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "type": "single",
        "prompt": qid,
        "options": [
            {"id": "a", "text": "A", "correct": True},
            {"id": "b", "text": "B"},
        ],
    }


def _module(mid: str, *qids: str) -> dict[str, Any]:
    return {"id": mid, "time_limit_sec": 600, "questions": [_question(q) for q in qids]}


def _exam(adaptive: bool = True) -> ExamBlock:
    return ExamBlock.model_validate(
        {
            "id": "e",
            "kind": "sat",
            "scaling": {"min_score": 200, "max_score": 800},
            "sections": [
                {
                    "id": "rw",
                    "adaptive": adaptive,
                    "modules": [
                        _module("m1", "q1", "q2"),
                        _module("hard", "q3", "q4"),
                        _module("easy", "q5", "q6"),
                    ],
                }
            ],
        }
    )


def _take(block: ExamBlock, sitting: ExamSitting, answer: str, at: datetime) -> str:
    following = next_module(block, sitting.runs)
    assert following is not None
    run = start_run(*following, at)
    sitting.runs.append(run)
    module = following[1]
    run.answers = {q.id: {"option_ids": [answer]} for q in module.questions}
    close_run(run, module, at + timedelta(minutes=1), late=False)
    return module.id


def test_adaptive_section_routes_by_first_module_score() -> None:
    block = _exam()
    strong = ExamSitting(revision_id="r", started_at=NOW, runs=[])
    assert _take(block, strong, "a", NOW) == "m1"
    assert _take(block, strong, "a", NOW) == "hard"
    assert next_module(block, strong.runs) is None
    weak = ExamSitting(revision_id="r", started_at=NOW, runs=[])
    _take(block, weak, "b", NOW)
    assert _take(block, weak, "a", NOW) == "easy"


def test_plain_section_takes_every_module() -> None:
    block = _exam(adaptive=False)
    sitting = ExamSitting(revision_id="r", started_at=NOW, runs=[])
    taken = [_take(block, sitting, "a", NOW) for _ in range(3)]
    assert taken == ["m1", "hard", "easy"]


def test_scaled_score_is_linear_and_easy_path_is_capped() -> None:
    block = _exam()
    best = ExamSitting(revision_id="r", started_at=NOW, runs=[])
    _take(block, best, "a", NOW)
    _take(block, best, "a", NOW)
    assert section_scores(block, best)[0].scaled == 800
    weak = ExamSitting(revision_id="r", started_at=NOW, runs=[])
    _take(block, weak, "b", NOW)
    _take(block, weak, "a", NOW)
    # half the points on the easier path: 200 + 600 * 0.5 * 0.75
    assert section_scores(block, weak)[0].scaled == 425
    assert exam_max_points(block) == Decimal(4)


def test_deadline_grace_then_late_close() -> None:
    block = _exam()
    section, module = find_module(block, "m1")
    sitting = ExamSitting(
        revision_id="r", started_at=NOW, runs=[start_run(section, module, NOW)]
    )
    run = sitting.runs[0]
    run.answers = {"q1": {"option_ids": ["a"]}}
    end = run.deadline_at
    assert accepts_answers(run, end + GRACE)
    assert not close_expired(block, sitting, end + GRACE)
    assert close_expired(block, sitting, end + GRACE + timedelta(seconds=1))
    assert run.late and run.submitted_at == end and run.score == Decimal(1)
    restored = ExamSitting.from_json(sitting.to_json())
    assert restored.runs[0].score == Decimal(1) and restored.current is None
