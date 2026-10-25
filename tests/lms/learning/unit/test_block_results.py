"""H5P xAPI results and interactive video answers kept in the step state."""

from typing import Any

from app.modules.lms.domain.learning.block_results import (
    XAPI_ANSWERED,
    XAPI_COMPLETED,
    map_xapi,
    merge_h5p,
    record_answer,
)
from app.modules.lms.domain.step_content import (
    InteractiveVideoBlock,
    Option,
    StepContent,
)
from app.modules.lms.domain.student_render import render_step

import pytest
from pydantic import ValidationError


def statement(verb: str, **result: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"verb": {"id": verb}, "result": result}


def video() -> InteractiveVideoBlock:
    return InteractiveVideoBlock.model_validate(
        {
            "id": "iv",
            "url": "https://youtu.be/abc",
            "interactions": [
                {
                    "id": "q2",
                    "at_sec": 30,
                    "text": "Two?",
                    "points": 2,
                    "options": [
                        {"id": "a", "text": "A", "correct": True},
                        {"id": "b", "text": "B"},
                    ],
                },
                {"id": "n", "at_sec": 5, "kind": "note", "text": "Look"},
                {
                    "id": "q1",
                    "at_sec": 10,
                    "text": "Poll",
                    "options": [{"id": "x", "text": "X"}, {"id": "y", "text": "Y"}],
                },
            ],
        }
    )


def test_completed_root_statement_maps_to_a_score() -> None:
    result = map_xapi(
        statement(XAPI_COMPLETED, score={"raw": 3, "max": 4}, completion=True)
    )
    assert result is not None
    assert (result.score, result.max_score, result.completed) == (3, 4, True)
    assert result.pct == 75


def test_sub_content_and_other_verbs_are_ignored() -> None:
    child = statement(XAPI_ANSWERED, score={"raw": 1, "max": 1})
    child["context"] = {"contextActivities": {"parent": [{"id": "root"}]}}
    assert map_xapi(child) is None
    assert map_xapi(statement("http://adlnet.gov/expapi/verbs/interacted")) is None
    assert map_xapi({"verb": {"id": XAPI_COMPLETED}}) is None


def test_scaled_score_and_answered_without_completion() -> None:
    result = map_xapi(statement(XAPI_ANSWERED, score={"scaled": 0.5}))
    assert result is not None
    assert (result.score, result.max_score, result.completed) == (50, 100, False)


def test_merge_keeps_the_best_score_and_sticky_completion() -> None:
    first = merge_h5p(None, _h5p(4, 4, True), passing_pct=60)
    worse = merge_h5p(first, _h5p(1, 4, False), passing_pct=60)
    assert first["passed"] is True
    assert worse["score"] == 4 and worse["completed"] and worse["passed"]
    failed = merge_h5p(None, _h5p(1, 4, True), passing_pct=60)
    assert failed["passed"] is False


def _h5p(score: float, top: float, done: bool) -> Any:  # noqa: ANN401
    result = map_xapi(
        statement(XAPI_COMPLETED, score={"raw": score, "max": top}, completion=done)
    )
    assert result is not None
    return result


def test_interactions_keep_their_order_and_render_sorted_by_time() -> None:
    assert [i.id for i in video().interactions] == ["q2", "n", "q1"]
    rendered = render_step(StepContent(title="t", blocks=[video()]), revision_id="r")
    assert [i["id"] for i in rendered["blocks"][0]["interactions"]] == ["n", "q1", "q2"]


def test_answers_are_scored_and_only_the_first_counts() -> None:
    block = video()
    wrong = record_answer(block, None, "q2", ["b"])
    again = record_answer(block, wrong, "q2", ["a"])
    done = record_answer(block, again, "q1", ["y"])

    assert wrong["answers"]["q2"] == {"option_ids": ["b"], "correct": False}
    assert again["score"] == 0 and not again["completed"]
    assert done["answers"]["q1"]["correct"] is True  # a poll accepts any choice
    assert (done["score"], done["max_score"], done["completed"]) == (1, 3, True)


def test_notes_are_not_questions() -> None:
    with pytest.raises(KeyError):
        record_answer(video(), None, "n", ["a"])


def test_student_render_hides_correct_options() -> None:
    rendered = render_step(StepContent(title="t", blocks=[video()]), revision_id="r")
    options = rendered["blocks"][0]["interactions"][2]["options"]
    assert options == [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]


def test_links_need_http_and_uploads_need_a_file() -> None:
    with pytest.raises(ValidationError):
        InteractiveVideoBlock.model_validate(
            {"interactions": [{"at_sec": 1, "kind": "link", "url": "javascript:x"}]}
        )
    with pytest.raises(ValidationError):
        InteractiveVideoBlock(source="upload")
    note = InteractiveVideoBlock.model_validate(
        {"interactions": [{"at_sec": 1, "kind": "note", "options": [Option(text="a")]}]}
    )
    assert note.interactions[0].options == []
