"""Step content documents: hashing and server-assigned ids (LMS-23)."""

import json
from typing import Any

from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    StepContent,
    TestBlock,
    TextBlock,
    assign_ids,
    canonical_hash,
)

import pytest
from pydantic import ValidationError

# The example document of README -> Course versioning.
EXAMPLE: dict[str, Any] = {
    "title": "Derivative rules",
    "blocks": [
        {"id": "b7f3Kq2x", "type": "text", "markdown": "The derivative of ..."},
        {
            "id": "b91cWm4r",
            "type": "test",
            "config": {
                "max_attempts": 3,
                "passing_score_pct": 60,
                "shuffle_questions": True,
                "shuffle_options": True,
                "pool_size": 5,
                "time_limit_sec": 600,
                "cooldown_sec": 300,
                "show_answers": "after_pass",
            },
            "questions": [
                {
                    "id": "q4Nz8Wp1",
                    "type": "single",
                    "prompt": "(x²)′ = ?",
                    "points": 1,
                    "explanation": "Power rule.",
                    "options": [
                        {
                            "id": "o9Tr2Ck6",
                            "text": "2x",
                            "correct": True,
                            "pinned": False,
                        },
                        {
                            "id": "o3Hb7Yd2",
                            "text": "x",
                            "correct": False,
                            "pinned": False,
                        },
                    ],
                },
                {
                    "id": "q8Fj3Rs5",
                    "type": "number",
                    "prompt": "f(x)=3x, f′(5)=?",
                    "points": 1,
                    "answer": {"value": 3, "tolerance": 0},
                },
            ],
        },
        {
            "id": "bc4dZ6vN",
            "type": "flashcards",
            "cards": [
                {"id": "c2Gx9Ue4", "front": "Power rule", "back": "(xⁿ)′ = n·xⁿ⁻¹"}
            ],
        },
    ],
}
KNOWN_IDS = {
    "b7f3Kq2x",
    "b91cWm4r",
    "q4Nz8Wp1",
    "o9Tr2Ck6",
    "o3Hb7Yd2",
    "q8Fj3Rs5",
    "bc4dZ6vN",
    "c2Gx9Ue4",
}


def _all_ids(content: StepContent) -> list[str]:
    """Collect every id of the content in document order."""
    ids: list[str] = []
    for block in content.blocks:
        ids.append(block.id)
        if isinstance(block, TestBlock):
            for question in block.questions:
                ids.append(question.id)
                ids.extend(option.id for option in question.options or [])
        elif isinstance(block, FlashcardsBlock):
            ids.extend(card.id for card in block.cards)
    return ids


def test_readme_example_is_valid_and_keeps_its_structure() -> None:
    content = StepContent.model_validate(EXAMPLE)

    assert [type(block) for block in content.blocks] == [
        TextBlock,
        TestBlock,
        FlashcardsBlock,
    ]
    assert content.blocks[1].config.show_answers == "after_pass"


def test_unknown_block_type_is_rejected() -> None:
    bad = {"title": "t", "blocks": [{"id": "x", "type": "audio"}]}

    with pytest.raises(ValidationError):
        StepContent.model_validate(bad)


def test_hash_is_a_sha256_hex_digest() -> None:
    digest = canonical_hash(StepContent.model_validate(EXAMPLE))

    assert len(digest) == 64
    int(digest, 16)


def test_hash_is_stable_across_key_order() -> None:
    reordered = json.loads(json.dumps(EXAMPLE, sort_keys=True))
    reversed_blocks_keys = {k: reordered[k] for k in sorted(reordered, reverse=True)}

    first = canonical_hash(StepContent.model_validate(EXAMPLE))
    second = canonical_hash(StepContent.model_validate(reversed_blocks_keys))

    assert first == second


def test_hash_changes_when_the_content_changes() -> None:
    changed = json.loads(json.dumps(EXAMPLE))
    changed["blocks"][0]["markdown"] = "Something else"

    assert canonical_hash(StepContent.model_validate(changed)) != canonical_hash(
        StepContent.model_validate(EXAMPLE)
    )


def test_known_ids_are_kept() -> None:
    content = StepContent.model_validate(EXAMPLE)

    result = assign_ids(content, set(KNOWN_IDS))

    assert result == content


def test_empty_string_ids_are_treated_like_missing_ids() -> None:
    """MCP tools send "" for new blocks, questions, options and cards."""
    raw = {
        "title": "t",
        "blocks": [
            {"id": "", "type": "text", "markdown": "a"},
            {"id": "", "type": "text", "markdown": "b"},
            {
                "id": "",
                "type": "test",
                "questions": [
                    {
                        "id": "",
                        "type": "single",
                        "prompt": "p",
                        "options": [
                            {"id": "", "text": "a", "correct": True},
                            {"id": "", "text": "b"},
                        ],
                    }
                ],
            },
            {
                "id": "",
                "type": "flashcards",
                "cards": [{"id": "", "front": "f", "back": "b"}],
            },
        ],
    }

    # Several "" in one content are not duplicates, even if "" is "known".
    ids = _all_ids(assign_ids(StepContent.model_validate(raw), {""}))

    assert len(ids) == 8
    assert len(set(ids)) == 8
    assert all(len(value) == 8 for value in ids)


def test_missing_ids_get_fresh_eight_character_ids() -> None:
    raw = {
        "title": "t",
        "blocks": [
            {"type": "text", "markdown": "a"},
            {
                "type": "test",
                "questions": [
                    {
                        "type": "single",
                        "prompt": "p",
                        "options": [{"text": "a", "correct": True}, {"text": "b"}],
                    }
                ],
            },
            {"type": "flashcards", "cards": [{"front": "f", "back": "b"}]},
        ],
    }

    ids = _all_ids(assign_ids(StepContent.model_validate(raw), set()))

    assert len(ids) == 7
    assert len(set(ids)) == 7
    assert all(len(value) == 8 for value in ids)


def test_unknown_ids_are_replaced_and_known_ids_stay() -> None:
    raw = json.loads(json.dumps(EXAMPLE))
    raw["blocks"][0]["id"] = "invented1"
    content = StepContent.model_validate(raw)

    result = assign_ids(content, set(KNOWN_IDS))

    assert result.blocks[0].id != "invented1"
    assert len(result.blocks[0].id) == 8
    assert result.blocks[1].id == "b91cWm4r"


def test_new_ids_never_collide_with_existing_ones() -> None:
    raw = {
        "title": "t",
        "blocks": [{"type": "text", "markdown": str(i)} for i in range(50)],
    }
    existing = {"other001", "other002"}

    ids = _all_ids(assign_ids(StepContent.model_validate(raw), existing))

    assert not set(ids) & existing
    assert len(set(ids)) == 50


def test_duplicate_ids_inside_one_content_are_rejected() -> None:
    raw = json.loads(json.dumps(EXAMPLE))
    raw["blocks"][0]["id"] = "q4Nz8Wp1"  # the id of a question

    with pytest.raises(ValueError, match="duplicate"):
        assign_ids(StepContent.model_validate(raw), set(KNOWN_IDS))


def test_assign_ids_does_not_change_its_input() -> None:
    content = StepContent.model_validate({"title": "t", "blocks": [{"type": "text"}]})

    assign_ids(content, set())

    assert content.blocks[0].id == ""
