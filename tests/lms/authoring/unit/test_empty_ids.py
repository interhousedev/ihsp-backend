"""LMS-23: an empty-string ID means the same as a missing ID."""

from typing import Any

from app.modules.lms.domain.authoring.content_edit import (
    collect_ids,
    strip_empty_ids,
    with_block_appended,
    with_question_appended,
)
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    StepContent,
    TestBlock,
    assign_ids,
)

EMPTY_IDS: dict[str, Any] = {
    "title": "Rules",
    "blocks": [
        {"id": "", "type": "text", "markdown": "A"},
        {"id": "", "type": "text", "markdown": "B"},
        {
            "id": "",
            "type": "test",
            "config": {},
            "questions": [
                {
                    "id": "",
                    "type": "single",
                    "prompt": "(x²)′ = ?",
                    "options": [
                        {"id": "", "text": "2x", "correct": True},
                        {"id": "", "text": "x"},
                    ],
                },
                {"id": "", "type": "number", "prompt": "3+4", "answer": {"value": 7}},
            ],
        },
        {
            "id": "",
            "type": "flashcards",
            "cards": [
                {"id": "", "front": "f1", "back": "b1"},
                {"id": "", "front": "f2", "back": "b2"},
            ],
        },
    ],
}


def _all_ids(content: StepContent) -> list[str]:
    ids: list[str] = []
    for block in content.blocks:
        ids.append(block.id)
        if isinstance(block, TestBlock):
            for question in block.questions:
                ids.append(question.id)
                ids.extend(o.id for o in question.options or [])
        elif isinstance(block, FlashcardsBlock):
            ids.extend(c.id for c in block.cards)
    return ids


def test_assign_ids_gives_every_empty_id_a_fresh_unique_server_id() -> None:
    """Several elements with `""` are not duplicates; each gets its own new ID."""
    content = StepContent.model_validate(EMPTY_IDS)

    assigned = assign_ids(content, set())

    ids = _all_ids(assigned)
    assert len(ids) == 10
    assert all(len(i) == 8 for i in ids)
    assert len(set(ids)) == 10


def test_missing_ids_and_empty_ids_are_treated_alike() -> None:
    """Both forms validate and both end up with server IDs."""
    without = StepContent.model_validate(strip_empty_ids(EMPTY_IDS))
    empty = StepContent.model_validate(EMPTY_IDS)

    assert _all_ids(without) == [""] * 10
    assert _all_ids(empty) == [""] * 10
    assert set(_all_ids(assign_ids(without, set()))) != {""}
    assert set(_all_ids(assign_ids(empty, set()))) != {""}


def test_known_ids_stay_while_empty_ones_are_replaced() -> None:
    """Existing elements keep their IDs; new ones in the same content get new IDs."""
    data = {
        "title": "T",
        "blocks": [
            {"id": "known001", "type": "text", "markdown": "old"},
            {"id": "", "type": "text", "markdown": "new"},
        ],
    }

    assigned = assign_ids(StepContent.model_validate(data), {"known001"})

    assert assigned.blocks[0].id == "known001"
    assert assigned.blocks[1].id not in ("", "known001")


def test_empty_ids_are_not_collected_as_ids() -> None:
    """They never count as "known" or as duplicates."""
    assert collect_ids(EMPTY_IDS) == set()


def test_strip_empty_ids_removes_empty_and_null_but_keeps_real_ids() -> None:
    """Only empty/null `id` keys disappear; the input is not changed."""
    value = {"id": "", "items": [{"id": None, "x": 1}, {"id": "keep", "x": 2}]}

    assert strip_empty_ids(value) == {"items": [{"x": 1}, {"id": "keep", "x": 2}]}
    assert value["id"] == ""


def test_add_only_edits_drop_empty_ids_from_what_they_append() -> None:
    """MCP additions arrive with `""` IDs and are stored without them."""
    base = {"title": "T", "blocks": [{"id": "b1", "type": "test", "questions": []}]}
    question = {"id": "", "type": "single", "prompt": "p", "options": [{"id": ""}]}

    with_block = with_block_appended(base, {"id": "", "type": "text", "markdown": "x"})
    with_question = with_question_appended(base, "b1", question)

    assert "id" not in with_block["blocks"][1]
    appended = with_question["blocks"][0]["questions"][0]
    assert "id" not in appended and "id" not in appended["options"][0]
