"""NB-19: checking the student's edits of a deck (`PUT …/slides`, § 3.4.6)."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import ProcessContext
from app.modules.notebooks.domain.artifacts.kinds.slides import HANDLER
from app.modules.notebooks.domain.artifacts.slides_edit import validate_slides_edit
from app.modules.notebooks.domain.errors import OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

LABELS = {"S1:P1", "S1:P2"}


def slide(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"s{n}",
        "layout": "bullets",
        "title": f"Topic {n}",
        "bullets": ["One", "Two"],
        "notes": "Notes",
        "refs": ["S1:P1"],
        **extra,
    }


def generated_deck() -> tuple[list[dict[str, Any]], set[str]]:
    """A deck as the generator stores it, with the keys of its refs_index."""
    side = {"heading": "Light", "bullets": ["a"]}
    raw = [
        {"layout": "title", "title": "Photosynthesis", "bullets": [], "refs": []},
        {
            "layout": "bullets",
            "title": "Stages",
            "bullets": ["a", "b"],
            "body": "Text",
            "refs": ["S1:P2"],
        },
        {
            "layout": "two_columns",
            "title": "Compare",
            "left": side,
            "right": side,
            "refs": ["S1:P1"],
        },
        {
            "layout": "quote",
            "title": "",
            "quote": {"text": "Light", "attribution": "Book"},
            "refs": ["S1:P3"],
        },
        {
            "layout": "table",
            "title": "Table",
            "table": {"columns": ["A", "B"], "rows": [["1", "2"]]},
            "refs": [],
        },
        {
            "layout": "summary",
            "title": "Summary",
            "bullets": ["Done"],
            "visual_hint": "Chart",
            "notes": "n",
            "refs": [],
        },
    ]
    out = HANDLER.process(
        {"title": "Photosynthesis", "slides": raw},
        HANDLER.parse_options({"length": "short"}),
        ProcessContext(two_source_pack(), "en", 1),
    )
    return out.content["slides"], set(out.refs_index)


def test_a_generated_deck_passes_unchanged() -> None:
    """NB-19: the stored shape is a fixed point of the edit rules."""
    slides, labels = generated_deck()

    assert validate_slides_edit(slides, labels) == slides


def test_reordering_and_deleting_keep_the_ids() -> None:
    """NB-19: a student moves and removes slides; ids stay."""
    slides, labels = generated_deck()
    edited = [slides[3], slides[0], slides[5]]

    result = validate_slides_edit(edited, labels)

    assert [s["id"] for s in result] == [
        slides[3]["id"],
        slides[0]["id"],
        slides[5]["id"],
    ]


def test_edited_text_is_capped_generously() -> None:
    """NB-19: the student's own words are kept up to generous caps (not the
    generation budget); absurd lengths are still cut."""
    long = " ".join(f"w{i}" for i in range(100))
    edited = slide(1, title="T" * 500, bullets=[long] * 15, notes="n" * 4000)

    [result] = validate_slides_edit([edited], LABELS)

    assert len(result["title"]) <= 120
    assert len(result["bullets"]) == 12
    assert len(result["bullets"][0].split()) <= 80
    assert len(result["notes"]) <= 1200


def test_a_student_bullet_longer_than_the_generation_budget_is_kept_whole() -> None:
    """NB-19: 30 words typed by the student are not cut to 12 or 20."""
    sentence = " ".join(f"слово{i}" for i in range(30))

    [result] = validate_slides_edit([slide(1, bullets=[sentence] * 9)], LABELS)

    assert result["bullets"] == [sentence] * 9


def test_refs_are_kept_only_when_they_exist_in_the_refs_index() -> None:
    """NB-19: refs outside the artifact's index are removed."""
    edited = slide(1, refs=["S1:P1", "S9:P9", "S1:P2"])

    [result] = validate_slides_edit([edited], {"S1:P2"})

    assert result["refs"] == ["S1:P2"]


def test_without_a_known_label_set_only_well_formed_labels_stay() -> None:
    """NB-19: `None` skips the lookup but not the format check."""
    edited = slide(1, refs=["S1:P1", "see page 4", "S2:P7", "S1:P1"])

    [result] = validate_slides_edit([edited], None)

    assert result["refs"] == ["S1:P1", "S2:P7"]


def test_an_empty_label_set_removes_every_ref() -> None:
    """NB-19: nothing exists in an empty index."""
    [result] = validate_slides_edit([slide(1)], set())

    assert result["refs"] == []


def test_a_deck_may_shrink_to_one_slide() -> None:
    """NB-19: 1 to 40 slides."""
    assert len(validate_slides_edit([slide(1)], LABELS)) == 1


def test_forty_slides_are_accepted_and_forty_one_are_not() -> None:
    """NB-19: the upper bound is 40."""
    assert len(validate_slides_edit([slide(n) for n in range(40)], LABELS)) == 40

    with pytest.raises(OutputInvalidError):
        validate_slides_edit([slide(n) for n in range(41)], LABELS)


def test_an_empty_deck_is_refused() -> None:
    """NB-19: at least one slide."""
    with pytest.raises(OutputInvalidError):
        validate_slides_edit([], LABELS)


@pytest.mark.parametrize("bad_id", [None, "", "  ", "a b", "x" * 41, 7])
def test_a_slide_needs_a_valid_id(bad_id: Any) -> None:
    """NB-19: ids are kept, so each slide must carry one."""
    edited = slide(1, id=bad_id)

    with pytest.raises(OutputInvalidError) as caught:
        validate_slides_edit([edited], LABELS)

    assert caught.value.problems[0].startswith("slide 1")


def test_repeated_ids_are_refused() -> None:
    """NB-19: ids are unique."""
    with pytest.raises(OutputInvalidError) as caught:
        validate_slides_edit([slide(1), slide(2, id="s1")], LABELS)

    assert caught.value.problems[0].startswith("slide 2")


def test_a_slide_that_cannot_be_repaired_refuses_the_edit() -> None:
    """NB-19: the student's content is never dropped silently."""
    broken = slide(2, layout="two_columns", left=None, right=None)

    with pytest.raises(OutputInvalidError) as caught:
        validate_slides_edit([slide(1), broken], LABELS)

    assert caught.value.problems == ["slide 2: layout two_columns lacks its fields"]


def test_every_problem_is_reported_at_once() -> None:
    """NB-19: the web can show all of them."""
    with pytest.raises(OutputInvalidError) as caught:
        validate_slides_edit(
            [slide(1, title=""), {"layout": "nope"}, slide(3, id="")], LABELS
        )

    assert len(caught.value.problems) == 3


def test_a_bullets_slide_cleared_by_the_student_is_refused() -> None:
    """NB-19: the layout needs content."""
    with pytest.raises(OutputInvalidError):
        validate_slides_edit([slide(1, bullets=[], body="")], LABELS)


def test_urls_in_visual_hints_are_stripped_in_edits_too() -> None:
    """NB-19: never a URL."""
    edited = slide(1, visual_hint="Picture https://x.example/a.png")

    [result] = validate_slides_edit([edited], LABELS)

    assert result["visual_hint"] == "Picture"


def test_unknown_fields_are_not_kept() -> None:
    """NB-19: the stored shape is closed."""
    edited = slide(1, evil="<script>", extra={"a": 1})

    [result] = validate_slides_edit([edited], LABELS)

    assert "evil" not in result
    assert "extra" not in result
