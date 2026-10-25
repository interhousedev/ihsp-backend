"""NB-14: helpers shared by the quiz, data table, slides and infographic kinds."""

from typing import Any

from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    clean_text,
    clip_chars,
    clip_words,
    document_title,
    expect_options,
    fit_text,
    norm_key,
    parse_options,
    refs_among,
    require_list,
    strip_urls,
    validate_items,
    validate_numbered,
)
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack
from tests.notebooks.unit.domain.pack_builder import make_pack

import pytest
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    size: int


def test_clean_text_collapses_whitespace_and_ignores_non_strings() -> None:
    assert clean_text("  a \n\t b  ") == "a b"
    assert clean_text(None) == ""
    assert clean_text(5) == ""


def test_clip_chars_ends_with_an_ellipsis_within_the_limit() -> None:
    assert clip_chars("abcdef", 6) == "abcdef"
    assert clip_chars("abcdefg", 6) == "abcde…"
    assert len(clip_chars("x" * 50, 10)) == 10


def test_clip_words_keeps_the_first_words() -> None:
    assert clip_words("one two three", 3) == "one two three"
    assert clip_words("one two three four", 3) == "one two three…"
    assert clip_words("one, two, three, four", 2) == "one, two…"


def test_fit_text_applies_words_then_characters() -> None:
    assert fit_text("  one   two three ", words=2) == "one two…"
    assert fit_text("abcdefghij", chars=5) == "abcd…"
    assert fit_text(None, words=3, chars=5) == ""


def test_strip_urls_removes_web_addresses_only() -> None:
    text = "See HTTPS://a.example/x?y=1 or http://b.example, and www.c.example/d now"

    assert strip_urls(text) == "See or and now"
    assert strip_urls("a plain hint") == "a plain hint"


def test_norm_key_ignores_case_punctuation_and_spacing() -> None:
    assert norm_key("  Which GAS, is released?! ") == norm_key("which gas is released")
    assert norm_key("Oʻsimlik") == norm_key("oʻsimlik")


def test_refs_among_keeps_known_labels_in_order_without_repeats() -> None:
    labels = {"S1:P1", "S1:P2", "S2:P1", "S2:P2"}

    result = refs_among(
        ["S2:P1", "[S1:P2]", "S9:P9", "S2:P1", "S1:P1", "S2:P2"], labels
    )

    assert result == ["S2:P1", "S1:P2", "S1:P1"]


def test_refs_among_without_labels_checks_only_the_format() -> None:
    assert refs_among(["S1:P1", "s1:p1", "S1P1", "x"], None) == ["S1:P1"]
    assert refs_among(None, {"S1:P1"}) == []


def test_parse_options_wraps_errors_in_a_details_list() -> None:
    with pytest.raises(InvalidOptionsError) as caught:
        parse_options(CommonOptions, {"language": "de", "source_ids": "x"})

    details = caught.value.params["details"]
    assert len(details) == 2
    assert any(d.startswith("language:") for d in details)


def test_parse_options_returns_the_model() -> None:
    options = parse_options(CommonOptions, {"language": "uz"})

    assert options.language == "uz"
    assert options.source_ids is None


def test_expect_options_rejects_another_kinds_options() -> None:
    with pytest.raises(TypeError):
        expect_options(CommonOptions(), Item)


def test_validate_numbered_keeps_positions_and_reports_the_rest() -> None:
    problems: list[str] = []
    raw: list[Any] = [
        {"name": "a", "size": 1},
        {"name": "b"},
        "junk",
        {"name": "d", "size": 4},
    ]

    valid = validate_numbered(Item, raw, problems, "thing")

    assert [(n, i.name) for n, i in valid] == [(1, "a"), (4, "d")]
    assert problems[0].startswith("thing 2: size:")
    assert problems[1].startswith("thing 3:")


def test_validate_items_never_echoes_the_input_in_the_problems() -> None:
    problems: list[str] = []

    validate_items(
        Item, [{"name": "SECRET TEXT", "size": "not a number"}], problems, "t"
    )

    assert problems
    assert "SECRET" not in problems[0]
    assert "not a number" not in problems[0]


def test_require_list_returns_the_list_or_fails() -> None:
    assert require_list({"a": [1, 2]}, "a") == [1, 2]
    with pytest.raises(OutputInvalidError):
        require_list({"a": {"x": 1}}, "a")
    with pytest.raises(OutputInvalidError):
        require_list({}, "a")


def test_require_list_looks_at_a_bounded_number_of_items() -> None:
    assert len(require_list({"a": list(range(1000))}, "a")) == 200


def test_document_title_prefers_the_model_then_the_first_source() -> None:
    pack = two_source_pack()

    assert document_title({"title": " My   title "}, pack, "Quiz") == "My title"
    assert document_title({"title": ""}, pack, "Quiz") == "Biology 10.pdf"
    assert document_title({}, make_pack([]), "Quiz") == "Quiz"
