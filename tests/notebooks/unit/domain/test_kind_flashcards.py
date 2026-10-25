"""NB-24: flash card options, task block and validation (§ 3.4.3)."""

from typing import Any
from uuid import uuid4

from app.modules.notebooks.domain.artifacts.kinds.flashcards import (
    HANDLER,
    FlashcardsOptions,
)
from app.modules.notebooks.domain.artifacts.registry import handler_for
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.domain.prompts.common import focus_clause
from tests.notebooks.unit.domain.pack_support import (
    assert_strict,
    make_ctx,
    make_pack,
)

import pytest


def options(**raw: Any) -> FlashcardsOptions:
    parsed = HANDLER.parse_options(raw)
    assert isinstance(parsed, FlashcardsOptions)
    return parsed


def card(
    front: str = "What is ATP?",
    back: str = "The energy currency of the cell.",
    *,
    refs: list[str] | None = None,
    hint: str | None = "Think of energy",
    topic: str | None = "Energy",
    card_id: str = "x",
) -> dict[str, Any]:
    return {
        "id": card_id,
        "front": front,
        "back": back,
        "hint": hint,
        "topic": topic,
        "refs": ["S1:P1"] if refs is None else refs,
    }


def process(cards: list[Any], count: str = "fewer", pack: Any = None) -> Any:
    data = {"title": "Cells: cards", "cards": cards}
    return HANDLER.process(data, options(count=count), make_ctx(pack))


def numbered(n: int, **kwargs: Any) -> list[dict[str, Any]]:
    return [card(f"Question number {i}?", f"Answer {i}.", **kwargs) for i in range(n)]


# - - - options and prompt - - -


def test_handler_is_registered_for_the_flashcards_kind() -> None:
    """NB-24: the registry finds the module's HANDLER."""
    assert handler_for(ArtifactKind.FLASHCARDS) is HANDLER
    assert HANDLER.schema_name == "nb_flashcards"
    assert HANDLER.kind is ArtifactKind.FLASHCARDS
    assert HANDLER.report_format(options()) is None


def test_defaults_are_standard_count_and_medium_difficulty() -> None:
    """NB-24: defaults are echoed back."""
    assert HANDLER.stored_options(options()) == {
        "count": "standard",
        "difficulty": "medium",
        "target_count": 20,
        "mode": "auto",
    }


def test_common_options_are_stored() -> None:
    """NB-24: language and source_ids."""
    source = uuid4()

    stored = HANDLER.stored_options(
        options(
            count="more", difficulty="hard", language="en", source_ids=[str(source)]
        )
    )

    assert stored == {
        "count": "more",
        "difficulty": "hard",
        "target_count": 35,
        "mode": "auto",
        "language": "en",
        "source_ids": [str(source)],
    }


@pytest.mark.parametrize(
    "bad", [{"count": "many"}, {"difficulty": "insane"}, {"language": "kk"}]
)
def test_invalid_options_raise_invalid_options_error(bad: dict[str, Any]) -> None:
    """NB-24: pydantic errors are wrapped with details."""
    with pytest.raises(InvalidOptionsError) as caught:
        HANDLER.parse_options(bad)

    assert caught.value.params["details"]


@pytest.mark.parametrize(
    ("count", "tokens"), [("fewer", 3500), ("standard", 6500), ("more", 11000)]
)
def test_max_tokens_by_count(count: str, tokens: int) -> None:
    """NB-24: § 3.4.0 table."""
    assert HANDLER.max_tokens(options(count=count)) == tokens
    assert HANDLER.input_cap_tokens(150_000) == 150_000


@pytest.mark.parametrize(
    ("count", "target"), [("fewer", 10), ("standard", 20), ("more", 35), (42, 42)]
)
def test_target_count_resolves_preset_or_exact_count(count: Any, target: int) -> None:
    """NB-24: an exact count overrides the size preset (target_count is plain)."""
    parsed = options(count=count)

    assert parsed.target_count == target
    assert HANDLER.stored_options(parsed)["target_count"] == target


@pytest.mark.parametrize("count", [0, 151, -3])
def test_exact_count_is_bounded_to_1_150(count: int) -> None:
    """NB-24: custom flash card counts are 1 to 150."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options({"count": count})


@pytest.mark.parametrize("count", [1, 150])
def test_exact_count_bounds_are_inclusive(count: int) -> None:
    """NB-24: 1 and 150 are allowed."""
    assert options(count=count).target_count == count


def test_max_tokens_grow_with_an_exact_count() -> None:
    """NB-24: a custom count gets a token budget that scales with it."""
    assert HANDLER.max_tokens(options(count=60)) > HANDLER.max_tokens(options(count=30))
    assert HANDLER.max_tokens(options(count=30)) >= 6500


def test_task_block_uses_the_exact_count() -> None:
    """NB-24: the requested number of cards is the exact count."""
    assert HANDLER.task_block(options(count=42), None).startswith(
        "Create 42 flash cards"
    )


def test_process_caps_at_the_exact_count() -> None:
    """NB-24: an exact count of 12 keeps 12 cards."""
    data = {"title": "Cells: cards", "cards": numbered(15)}

    output = HANDLER.process(data, options(count=12), make_ctx(None))

    assert len(output.content["cards"]) == 12


def test_strict_schema_requires_every_card_field() -> None:
    """NB-24: Schemas row; hint and topic are nullable but present."""
    schema = HANDLER.strict_schema()

    assert_strict(schema)
    item = schema["properties"]["cards"]["items"]
    assert list(item["properties"]) == ["id", "front", "back", "hint", "topic", "refs"]
    assert {"type": "null"} in item["properties"]["hint"]["anyOf"]
    assert {"type": "null"} in item["properties"]["topic"]["anyOf"]


@pytest.mark.parametrize(
    ("count", "number"), [("fewer", 10), ("standard", 20), ("more", 35)]
)
def test_task_block_asks_for_the_requested_number(count: str, number: int) -> None:
    """NB-24: 10 / 20 / 35 cards."""
    task = HANDLER.task_block(options(count=count), None)

    assert task.startswith(f"Create {number} flash cards")


@pytest.mark.parametrize(
    ("level", "clause"),
    [
        ("easy", "terms, definitions, dates and names"),
        ("medium", "explain, compare, cause and effect"),
        ("hard", "apply and reason across passages"),
    ],
)
def test_task_block_describes_the_difficulty(level: str, clause: str) -> None:
    """NB-24: the difficulty clause of prompts.common."""
    task = HANDLER.task_block(options(difficulty=level), None)

    assert f"Difficulty {level}: {clause}." in task


def test_task_block_states_the_card_rules() -> None:
    """NB-24: lengths, no duplicates, topic and hint."""
    task = HANDLER.task_block(options(), None)

    assert "at most 160 characters" in task and "at most 300 characters" in task
    assert "No duplicates" in task
    assert "`topic` is a 1-3 word group name" in task
    assert "must not give the answer away" in task
    assert "Cover the sources evenly, then add the standard facts of the topic" in task
    assert "Never ask what a heading says" in task


def test_task_block_appends_the_focus() -> None:
    """NB-24: the student's focus is a hint."""
    task = HANDLER.task_block(options(), "only Krebs cycle")

    assert task.endswith(focus_clause("only Krebs cycle"))


def test_default_title() -> None:
    """NB-24: "Flash cards: <notebook>"."""
    assert HANDLER.default_title("Biology", options()) == "Flash cards: Biology"


# - - - process: content shape - - -


def test_process_returns_the_flashcards_content_shape() -> None:
    """NB-24: {title, cards[{id, front, back, hint, topic, refs}]} and refs_index."""
    result = process([card(refs=["S1:P3"])])

    assert result.title == "Cells: cards"
    assert result.content == {
        "title": "Cells: cards",
        "cards": [
            {
                "id": "c1",
                "front": "What is ATP?",
                "back": "The energy currency of the cell.",
                "hint": "Think of energy",
                "topic": "Energy",
                "refs": ["S1:P3"],
            }
        ],
    }
    assert set(result.refs_index) == {"S1:P3"}
    assert result.refs_index["S1:P3"]["snippet"].startswith("Text of passage 3")


def test_process_rewrites_ids_as_c1_to_cn() -> None:
    """NB-24: ids are the server's."""
    result = process([card(f"Q{i}?", card_id=f"zzz{i}") for i in range(4)])

    assert [c["id"] for c in result.content["cards"]] == ["c1", "c2", "c3", "c4"]


def test_process_title_falls_back_to_a_plain_name() -> None:
    """NB-24: a missing title is not an error."""
    result = HANDLER.process({"cards": [card()]}, options(), make_ctx())

    assert result.title == "Flash cards"


def test_process_empty_hint_and_topic_become_none() -> None:
    """NB-24: no empty strings in stored cards."""
    result = process([card(hint="  ", topic="")])

    stored = result.content["cards"][0]
    assert stored["hint"] is None and stored["topic"] is None


def test_process_accepts_cards_without_optional_keys() -> None:
    """NB-24: hint, topic, id and refs may be missing."""
    result = process([{"front": "Q?", "back": "A."}], pack=make_pack())

    stored = result.content["cards"][0]
    assert stored["hint"] is None and stored["topic"] is None
    assert stored["id"] == "c1"
    assert stored["refs"] == []


# - - - process: text rules - - -


def test_process_trims_front_to_160_and_back_to_300_characters() -> None:
    """NB-24: lengths are trimmed, not rejected."""
    result = process([card("F" * 400, "B" * 900)])

    stored = result.content["cards"][0]
    assert len(stored["front"]) == 160 and stored["front"].endswith("…")
    assert len(stored["back"]) == 300 and stored["back"].endswith("…")


def test_process_collapses_whitespace_in_the_texts() -> None:
    """NB-24: one line per side."""
    result = process([card("  What\n is   ATP? ", "Energy\n\ncurrency")])

    stored = result.content["cards"][0]
    assert stored["front"] == "What is ATP?"
    assert stored["back"] == "Energy currency"


def test_process_drops_cards_with_an_empty_front_or_back() -> None:
    """NB-24: nothing to learn from them."""
    result = process([card("   ", "A"), card("Q?", ""), card("Real?", "Yes.")])

    assert [c["front"] for c in result.content["cards"]] == ["Real?"]


def test_process_dedupes_by_normalised_front() -> None:
    """NB-24: case, spaces and punctuation do not make a card new; first wins."""
    result = process(
        [
            card("What is ATP?", "First."),
            card("what  is ATP", "Second."),
            card("WHAT IS A.T.P.?!", "Third."),
            card("What is ADP?", "Fourth."),
        ]
    )

    assert [c["back"] for c in result.content["cards"]] == ["First.", "Fourth."]


def test_process_keeps_fronts_that_differ_in_digits_or_letters() -> None:
    """NB-24: only equal normalised fronts are duplicates."""
    result = process([card("Define H2O"), card("Define H3O"), card("Define CO2")])

    assert len(result.content["cards"]) == 3


def test_process_keeps_math_fronts_that_differ_only_in_a_sign() -> None:
    """NB-24: symbols are not punctuation: x+1 and x-1 are two cards."""
    result = process([card("Solve x+1=3"), card("Solve x-1=3"), card("Solve x^2=3")])

    assert len(result.content["cards"]) == 3


def test_process_dedupes_cyrillic_fronts() -> None:
    """NB-24: casefold works for Russian."""
    result = process([card("Что такое АТФ?"), card("что такое атф")])

    assert len(result.content["cards"]) == 1


# - - - process: counts - - -


@pytest.mark.parametrize(
    ("count", "limit"), [("fewer", 10), ("standard", 20), ("more", 35)]
)
def test_process_truncates_to_the_requested_count(count: str, limit: int) -> None:
    """NB-24: more than N cards are cut to N."""
    result = process(numbered(50), count=count)

    cards = result.content["cards"]
    assert len(cards) == limit
    assert cards[-1]["id"] == f"c{limit}"
    assert cards[0]["front"] == "Question number 0?"


def test_process_accepts_fewer_cards_than_requested() -> None:
    """NB-24: thin sources give fewer cards instead of invented ones."""
    result = process(numbered(3), count="standard")

    assert len(result.content["cards"]) == 3


def test_process_without_a_single_valid_card_is_invalid() -> None:
    """NB-24: nothing usable triggers a repair."""
    with pytest.raises(OutputInvalidError):
        process([card("", "A"), card("Q", "  ")])


@pytest.mark.parametrize("cards", [None, "x", {}, []])
def test_process_requires_a_non_empty_card_list(cards: Any) -> None:
    """NB-24: a missing or empty list is invalid."""
    with pytest.raises(OutputInvalidError):
        HANDLER.process({"title": "T", "cards": cards}, options(), make_ctx())


def test_process_reports_the_problems_of_unreadable_cards() -> None:
    """NB-24: the repair prompt names the broken items."""
    with pytest.raises(OutputInvalidError) as caught:
        process(["nope", {"front": "only a front"}])

    assert any(p.startswith("card 1:") for p in caught.value.problems)
    assert any(p.startswith("card 2:") for p in caught.value.problems)


def test_process_keeps_good_cards_when_others_are_unreadable() -> None:
    """NB-24: soft repair."""
    result = process(["nope", card("Q?", "A."), {"back": "only a back"}])

    assert [c["front"] for c in result.content["cards"]] == ["Q?"]


# - - - process: refs - - -


def test_process_drops_cards_with_invented_refs_but_keeps_honest_ones() -> None:
    """NB-24: all refs invalid -> dropped (enough valid ones remain); [] is honest."""
    good = numbered(6, refs=["S1:P2"])
    bad = [card("Invented?", "Yes.", refs=["S7:P7"]), card("No refs?", "No.", refs=[])]

    result = process([*bad, *good])

    fronts = [c["front"] for c in result.content["cards"]]
    assert len(fronts) == 7
    assert "Invented?" not in fronts and "No refs?" in fronts
    assert result.content["cards"][0]["refs"] == []


def test_process_keeps_every_card_when_dropping_would_leave_under_half() -> None:
    """NB-24: keep_items_with_refs with requested = N (10 for fewer)."""
    cards = [card(f"Q{i}?", f"A{i}", refs=["S9:P9"]) for i in range(8)]
    cards += [card("Valid?", "Yes.", refs=["S1:P1"])]

    result = process(cards, count="fewer")

    stored = result.content["cards"]
    assert len(stored) == 9
    assert stored[0]["refs"] == []
    assert set(result.refs_index) == {"S1:P1"}


def test_process_drops_when_at_least_half_of_the_request_survives() -> None:
    """NB-24: exactly half is enough."""
    cards = [card(f"Q{i}?", f"A{i}", refs=["S9:P9"]) for i in range(5)]
    cards += [card(f"Valid{i}?", "Yes.", refs=["S1:P1"]) for i in range(5)]

    result = process(cards, count="fewer")

    assert len(result.content["cards"]) == 5


def test_process_filters_refs_and_builds_refs_index_for_used_labels_only() -> None:
    """NB-24: invalid labels are removed from the card; the index is minimal."""
    result = process(
        [card(refs=["S1:P2", "S3:P3", "S1:P2"]), card("Other?", "A.", refs=["S1:P5"])]
    )

    assert result.content["cards"][0]["refs"] == ["S1:P2"]
    assert set(result.refs_index) == {"S1:P2", "S1:P5"}
    assert result.refs_index["S1:P5"]["passage_id"]


def test_process_resolves_refs_across_sources() -> None:
    """NB-24: labels of the second source use its title."""
    pack = make_pack((2, 2), titles=("Lesson", "Notes"))

    result = process([card(refs=["S2:P1"])], pack=pack)

    assert result.refs_index["S2:P1"]["source_title"] == "Notes"
