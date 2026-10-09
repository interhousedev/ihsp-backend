"""NB-14, NB-20: the infographic kind (§ 3.4.7): options, blocks, trimming, refs."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import (
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.infographic import HANDLER
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

CTX = ProcessContext(pack=two_source_pack(), language="en", seed=1)


def block(n: int = 1, kind: str = "list", **extra: Any) -> dict[str, Any]:
    """A valid block of the given type with one item."""
    return {
        "type": kind,
        "title": f"Block {n}",
        "items": [{"head": f"Head {n}", "body": f"Body {n}"}],
        "refs": ["S1:P1"],
        **extra,
    }


def comparison(**extra: Any) -> dict[str, Any]:
    return {
        "type": "comparison",
        "title": "Two stages",
        "items": [],
        "columns": [
            {"title": "Light", "points": ["a", "b"]},
            {"title": "Calvin", "points": ["c"]},
        ],
        "refs": ["S1:P2"],
        **extra,
    }


def words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


def blocks(count: int) -> list[dict[str, Any]]:
    return [block(n) for n in range(1, count + 1)]


def run(items: list[dict[str, Any]], **options: Any) -> ProcessedOutput:
    document = {
        "title": "Photosynthesis at a glance",
        "subtitle": "Grade 10",
        "footer": "Source: Lesson 5",
        "blocks": items,
    }
    return HANDLER.process(document, HANDLER.parse_options(options), CTX)


def test_options_defaults_are_filled() -> None:
    """NB-14: portrait, standard, clean."""
    stored = HANDLER.stored_options(HANDLER.parse_options({}))

    assert stored == {
        "orientation": "portrait",
        "detail": "standard",
        "style": "clean",
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"orientation": "wide"},
        {"detail": "huge"},
        {"style": "neon"},
        {"language": "xx"},
    ],
)
def test_invalid_options_raise(raw: dict[str, Any]) -> None:
    """NB-14: unknown values are rejected."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options(raw)


def test_every_orientation_and_style_is_accepted() -> None:
    """NB-14: three orientations, five styles."""
    for orientation in ("portrait", "landscape", "square"):
        HANDLER.parse_options({"orientation": orientation})
    for style in ("clean", "sketch", "bento", "scientific", "playful"):
        HANDLER.parse_options({"style": style})


def test_input_cap_never_exceeds_one_hundred_thousand_tokens() -> None:
    """NB-14: infographics read at most 100k tokens."""
    assert HANDLER.input_cap_tokens(150_000) == 100_000
    assert HANDLER.input_cap_tokens(100_000) == 100_000
    assert HANDLER.input_cap_tokens(60_000) == 60_000


def test_handler_constants() -> None:
    """NB-14: token budget, schema name, no report format, title."""
    options = HANDLER.parse_options({})

    assert HANDLER.max_tokens(options) == 3500
    assert HANDLER.schema_name == "nb_infographic"
    assert HANDLER.kind.value == "infographic"
    assert HANDLER.report_format(options) is None
    assert HANDLER.default_title("Biology", options) == "Infographic: Biology"


@pytest.mark.parametrize(
    ("detail", "count"),
    [
        ("concise", "5 blocks"),
        ("standard", "6 to 7 blocks"),
        ("detailed", "8 to 9 blocks"),
    ],
)
def test_task_block_names_the_number_of_blocks(detail: str, count: str) -> None:
    """NB-20: 5 / 6-7 / 8-9 blocks."""
    task = HANDLER.task_block(HANDLER.parse_options({"detail": detail}), "only dates")

    assert count in task
    assert "only dates" in task
    assert "at most 6 words" in task
    assert "at most 18 words" in task
    assert "Leave the layout to the renderer" in task


def test_blocks_are_stored_as_in_the_contract() -> None:
    """NB-20: InfographicContent of § 4.4."""
    out = run(blocks(6))

    assert out.title == "Photosynthesis at a glance"
    assert out.content["subtitle"] == "Grade 10"
    assert out.content["footer"] == "Source: Lesson 5"
    first = out.content["blocks"][0]
    assert first == {
        "type": "list",
        "title": "Block 1",
        "items": [{"head": "Head 1", "body": "Body 1"}],
        "refs": ["S1:P1"],
    }


def test_subtitle_and_footer_are_none_when_empty() -> None:
    """NB-20: both are optional."""
    document = {"title": "T", "subtitle": "  ", "blocks": blocks(5)}

    out = HANDLER.process(document, HANDLER.parse_options({}), CTX)

    assert out.content["subtitle"] is None
    assert out.content["footer"] is None


def test_unknown_block_types_are_dropped() -> None:
    """NB-20: only the eight types survive."""
    items = [*blocks(5), block(6, kind="poster")]

    out = run(items)

    assert len(out.content["blocks"]) == 5
    assert all(b["type"] != "poster" for b in out.content["blocks"])


@pytest.mark.parametrize(
    "kind", ["stat", "steps", "list", "timeline", "definition", "quote", "callout"]
)
def test_every_item_block_type_is_accepted(kind: str) -> None:
    """NB-20: seven types use `items`."""
    out = run([block(1, kind=kind), *blocks(4)])

    assert out.content["blocks"][0]["type"] == kind
    assert "columns" not in out.content["blocks"][0]


def test_comparison_keeps_its_columns() -> None:
    """NB-20: a comparison has `columns` of {title, points}."""
    out = run([comparison(), *blocks(4)])

    stored = out.content["blocks"][0]
    assert stored["type"] == "comparison"
    assert stored["columns"] == [
        {"title": "Light", "points": ["a", "b"]},
        {"title": "Calvin", "points": ["c"]},
    ]
    assert stored["items"] == []


def test_a_comparison_needs_two_columns() -> None:
    """NB-20: one column is not a comparison."""
    one = comparison(columns=[{"title": "Light", "points": ["a"]}])
    empty = comparison(columns=None)

    out = run([one, empty, *blocks(5)])

    assert all(b["type"] != "comparison" for b in out.content["blocks"])


def test_a_comparison_has_at_most_three_columns_of_six_points() -> None:
    """NB-20: two or three columns."""
    wide = comparison(
        columns=[
            {"title": f"C{i}", "points": [f"p{j}" for j in range(9)]} for i in range(5)
        ]
    )

    out = run([wide, *blocks(4)])

    columns = out.content["blocks"][0]["columns"]
    assert len(columns) == 3
    assert len(columns[0]["points"]) == 6


def test_a_block_without_usable_items_is_dropped_and_reported() -> None:
    """NB-20: an empty block shows nothing."""
    empty = block(1, items=[{"head": " ", "body": ""}])

    with pytest.raises(OutputInvalidError) as caught:
        run([empty, block(2)])

    assert any(p.startswith("block 1") for p in caught.value.problems)


def test_titles_are_cut_to_six_words_and_bodies_to_eighteen() -> None:
    """NB-20: titles at most 6 words, bodies at most 18."""
    item = {"head": words(12), "body": words(40)}
    long = block(1, title=words(20), items=[item])

    out = run([long, *blocks(4)])

    stored = out.content["blocks"][0]
    assert len(stored["title"].split()) == 6
    assert len(stored["items"][0]["head"].split()) == 6
    assert len(stored["items"][0]["body"].split()) == 18


def test_comparison_points_and_titles_are_trimmed_too() -> None:
    """NB-20: the same caps apply inside columns."""
    columns = [
        {"title": words(30), "points": [words(30)]},
        {"title": "B", "points": ["x"]},
    ]

    out = run([comparison(columns=columns), *blocks(4)])

    first = out.content["blocks"][0]["columns"][0]
    assert len(first["title"].split()) == 6
    assert len(first["points"][0].split()) == 18


def test_items_are_capped_by_block_type() -> None:
    """NB-20: a callout and a quote have one item, a stat at most four."""
    many = [{"head": f"h{i}", "body": f"b{i}"} for i in range(10)]

    out = run(
        [
            block(1, kind="callout", items=many),
            block(2, kind="stat", items=many),
            *blocks(3),
        ]
    )

    assert len(out.content["blocks"][0]["items"]) == 1
    assert len(out.content["blocks"][1]["items"]) == 4


def test_an_item_may_have_only_a_head_or_only_a_body() -> None:
    """NB-20: list items may have no head; other pieces may have no body."""
    items = [{"head": None, "body": "Only body"}, {"head": "Only head", "body": None}]

    out = run([block(1, items=items), *blocks(4)])

    assert out.content["blocks"][0]["items"] == [
        {"head": "", "body": "Only body"},
        {"head": "Only head", "body": ""},
    ]


def test_a_title_may_be_empty() -> None:
    """NB-20: a stat block has no title in the doc example."""
    out = run([block(1, kind="stat", title=""), *blocks(4)])

    assert out.content["blocks"][0]["title"] == ""


@pytest.mark.parametrize(
    ("detail", "kept"), [("concise", 5), ("standard", 7), ("detailed", 9)]
)
def test_extra_blocks_are_trimmed_to_the_detail(detail: str, kept: int) -> None:
    """NB-20: 5 / 6-7 / 8-9 blocks; extra ones are cut from the end."""
    out = run(blocks(12), detail=detail)

    assert len(out.content["blocks"]) == kept
    assert out.content["blocks"][0]["title"] == "Block 1"


def test_three_valid_blocks_are_enough_and_two_are_not() -> None:
    """NB-20: fewer than 3 valid blocks -> OutputInvalidError."""
    assert len(run(blocks(3)).content["blocks"]) == 3

    with pytest.raises(OutputInvalidError):
        run(blocks(2))


def test_blocks_must_be_a_list() -> None:
    """NB-20: a document without blocks is invalid."""
    with pytest.raises(OutputInvalidError):
        HANDLER.process({"title": "x", "blocks": None}, HANDLER.parse_options({}), CTX)


def test_refs_are_resolved_and_indexed() -> None:
    """NB-20: valid labels stay, the index covers them."""
    items = [block(1, refs=["S1:P3", "S2:P1", "S9:P9"]), *blocks(5)]

    out = run(items)

    assert out.content["blocks"][0]["refs"] == ["S1:P3", "S2:P1"]
    assert set(out.refs_index) == {"S1:P1", "S1:P3", "S2:P1"}
    assert out.refs_index["S2:P1"]["source_kind"] == "file"


def test_blocks_without_valid_refs_are_dropped_when_enough_remain() -> None:
    """NB-20: keep_items_with_refs drops the unsupported block."""
    items = [*blocks(6), block(7, refs=["S9:P9"])]

    out = run(items)

    assert len(out.content["blocks"]) == 6
    assert all(b["refs"] for b in out.content["blocks"])


def test_blocks_are_kept_when_the_sources_are_thin() -> None:
    """NB-20: fewer than half with refs -> all blocks stay."""
    items = [block(1), *[block(n, refs=[]) for n in range(2, 7)]]

    out = run(items)

    assert len(out.content["blocks"]) == 6


def test_the_doc_example_is_accepted() -> None:
    """NB-20: the three blocks of § 3.4.7 give a valid (short) infographic."""
    example = [
        {
            "type": "stat",
            "title": "",
            "items": [{"head": "6CO2 + 6H2O", "body": "→ C6H12O6 + 6O2"}],
            "refs": ["S1:P2"],
        },
        {
            "type": "steps",
            "title": "Process",
            "items": [
                {"head": "Absorb light", "body": "Chlorophyll captures it"},
                {"head": "Split water", "body": "Releases O2"},
            ],
            "refs": ["S1:P3"],
        },
        {
            "type": "comparison",
            "title": "Two stages",
            "columns": [
                {"title": "Light", "points": ["…"]},
                {"title": "Calvin", "points": ["…"]},
            ],
            "items": [],
            "refs": ["S1:P1"],
        },
    ]

    out = run(example)

    assert [b["type"] for b in out.content["blocks"]] == ["stat", "steps", "comparison"]
