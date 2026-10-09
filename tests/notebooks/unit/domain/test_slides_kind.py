"""NB-14, NB-19: the slide deck kind (§ 3.4.6): options, layouts, counts, trimming."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import (
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.slides import HANDLER
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

CTX = ProcessContext(pack=two_source_pack(), language="en", seed=1)


def bullets_slide(n: int, **extra: Any) -> dict[str, Any]:
    """A valid ``bullets`` slide."""
    return {
        "id": f"m{n}",
        "layout": "bullets",
        "title": f"Topic {n}",
        "bullets": ["Light reactions", "Calvin cycle"],
        "notes": "Say this.",
        "visual_hint": "Two-box diagram",
        "refs": ["S1:P2"],
        **extra,
    }


def title_slide(**extra: Any) -> dict[str, Any]:
    return {
        "id": "t",
        "layout": "title",
        "title": "Photosynthesis",
        "bullets": [],
        "notes": "Welcome",
        "refs": [],
        **extra,
    }


def summary_slide(**extra: Any) -> dict[str, Any]:
    return {
        "id": "z",
        "layout": "summary",
        "title": "Summary",
        "bullets": ["Plants make glucose"],
        "notes": "Recap",
        "refs": ["S1:P1"],
        **extra,
    }


def deck(total: int) -> list[dict[str, Any]]:
    """A title slide, ``total - 2`` bullets slides and a summary slide."""
    return [
        title_slide(),
        *[bullets_slide(n) for n in range(total - 2)],
        summary_slide(),
    ]


def run(slides: list[dict[str, Any]], **options: Any) -> ProcessedOutput:
    document = {"title": "Photosynthesis", "subtitle": "Grade 10", "slides": slides}
    return HANDLER.process(document, HANDLER.parse_options(options), CTX)


def layouts(out: ProcessedOutput) -> list[str]:
    return [s["layout"] for s in out.content["slides"]]


def test_options_defaults_are_filled() -> None:
    """NB-14: presenter format, default length."""
    stored = HANDLER.stored_options(HANDLER.parse_options({}))

    assert stored == {"format": "presenter", "length": "default"}


@pytest.mark.parametrize(
    "raw", [{"format": "poster"}, {"length": "epic"}, {"language": "kk"}]
)
def test_invalid_options_raise(raw: dict[str, Any]) -> None:
    """NB-14: unknown values are rejected."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options(raw)


@pytest.mark.parametrize(
    ("length", "tokens"), [("short", 4000), ("default", 7000), ("long", 11000)]
)
def test_max_tokens_follow_the_length(length: str, tokens: int) -> None:
    """NB-14: § 3.4.0 token table."""
    assert HANDLER.max_tokens(HANDLER.parse_options({"length": length})) == tokens


def test_handler_constants() -> None:
    """NB-14: schema name, report format and input cap."""
    options = HANDLER.parse_options({})

    assert HANDLER.schema_name == "nb_slides"
    assert HANDLER.kind.value == "slides"
    assert HANDLER.report_format(options) is None
    assert HANDLER.input_cap_tokens(150_000) == 150_000
    assert HANDLER.default_title("Biology", options) == "Slides: Biology"


@pytest.mark.parametrize(
    ("length", "count"), [("short", 6), ("default", 10), ("long", 16)]
)
def test_task_block_names_the_slide_count(length: str, count: int) -> None:
    """NB-19: 6 / 10 / 16 slides."""
    task = HANDLER.task_block(HANDLER.parse_options({"length": length}), None)

    assert f"about {count} slides" in task


def test_task_block_describes_the_format_and_the_focus() -> None:
    """NB-19: presenter vs detailed wording, focus text, never a URL."""
    presenter = HANDLER.task_block(HANDLER.parse_options({}), "for grade 8")
    detailed = HANDLER.task_block(HANDLER.parse_options({"format": "detailed"}), None)

    assert "at most 5 `bullets`, each at most 12 words" in presenter
    assert "2 to 4 full sentences" in presenter
    assert "for grade 8" in presenter
    assert "at most 6 `bullets`, each at most 20 words" in detailed
    assert "at most 45 words" in detailed
    assert "never a URL" in detailed
    assert 'A "summary" slide last' in detailed


def test_task_block_gives_the_deck_outline_and_the_citation_rules() -> None:
    """NB-19: title, agenda, one idea per slide, summary, refs, plain text."""
    task = HANDLER.task_block(HANDLER.parse_options({"length": "short"}), None)

    for phrase in (
        'A "title" slide',
        'An "agenda" slide',
        "ONE idea",
        'A "summary" slide last',
        "S1 first, then S2",
        "every source at least one slide",
        "cites 1 to 3",
        "no Markdown",
        "never LaTeX",
        "between 4 and 8",
    ):
        assert phrase in task


def test_ids_are_rewritten_and_the_deck_fields_are_stored() -> None:
    """NB-19: ids s1..sn, title and subtitle."""
    out = run(deck(6))

    assert [s["id"] for s in out.content["slides"]] == [f"s{n}" for n in range(1, 7)]
    assert out.title == "Photosynthesis"
    assert out.content["title"] == "Photosynthesis"
    assert out.content["subtitle"] == "Grade 10"


def test_slides_without_refs_are_kept_and_the_index_has_the_used_labels() -> None:
    """NB-19: refs are checked but slides are not dropped for lacking them."""
    out = run(deck(6), length="short")

    assert out.content["slides"][0]["refs"] == []
    assert set(out.refs_index) == {"S1:P1", "S1:P2"}


def test_unknown_refs_are_removed() -> None:
    """NB-19: refs outside the pack are dropped."""
    out = run(
        [title_slide(), bullets_slide(1, refs=["S1:P2", "S5:P1"]), summary_slide()]
    )

    assert out.content["slides"][1]["refs"] == ["S1:P2"]


def test_too_many_slides_are_trimmed_from_the_end_keeping_the_summary() -> None:
    """NB-19: target + 2; the last slide stays the summary."""
    out = run(deck(14), length="short")

    slides = out.content["slides"]
    assert len(slides) == 8
    assert slides[0]["layout"] == "title"
    assert slides[-1]["layout"] == "summary"
    assert slides[-2]["title"] == "Topic 5"


def test_too_many_slides_without_a_summary_are_cut_at_the_limit() -> None:
    """NB-19: no summary -> plain cut."""
    slides = [title_slide(), *[bullets_slide(n) for n in range(12)]]

    out = run(slides, length="short")

    assert len(out.content["slides"]) == 8
    assert "summary" not in layouts(out)


def test_a_deck_within_two_of_the_target_is_not_changed() -> None:
    """NB-19: +-2 is fine."""
    assert len(run(deck(8), length="short").content["slides"]) == 8
    assert len(run(deck(4), length="short").content["slides"]) == 4


def test_fewer_slides_are_accepted_down_to_three() -> None:
    """NB-19: thin sources give a short deck."""
    out = run(deck(3), length="long")

    assert len(out.content["slides"]) == 3


def test_fewer_than_three_slides_is_an_invalid_output() -> None:
    """NB-19: fewer than three valid slides -> OutputInvalidError."""
    with pytest.raises(OutputInvalidError):
        run(deck(2))


def test_a_slide_that_cannot_be_repaired_is_dropped_and_reported() -> None:
    """NB-19: unrepairable slides are dropped; the problems name the slide."""
    broken = {"id": "x", "layout": "quote", "title": "", "notes": "", "refs": []}

    with pytest.raises(OutputInvalidError) as caught:
        run([title_slide(), broken])

    assert any(p.startswith("slide 2") for p in caught.value.problems)


def test_a_slide_with_an_unknown_layout_is_dropped() -> None:
    """NB-19: layouts are the seven of the doc."""
    out = run([*deck(5), {"layout": "poster", "title": "x", "refs": []}])

    assert len(out.content["slides"]) == 5


def test_two_columns_needs_both_sides() -> None:
    """NB-19: left and right are required."""
    side = {"heading": "Light", "bullets": ["a", "b"]}
    good = {"layout": "two_columns", "title": "Compare", "left": side, "right": side}
    half = {"layout": "two_columns", "title": "Compare", "left": side, "right": None}

    out = run([title_slide(), good, half, summary_slide()])

    assert layouts(out) == ["title", "two_columns", "summary"]
    stored = out.content["slides"][1]
    assert stored["left"] == side
    assert stored["right"] == side
    assert "bullets" not in stored


def test_quote_needs_a_text_and_keeps_an_empty_title() -> None:
    """NB-19: a quote slide may have an empty title but needs the quote."""
    good = {
        "layout": "quote",
        "title": "",
        "quote": {"text": "Light!", "attribution": "Teacher"},
        "refs": ["S1:P1"],
    }
    empty = {
        "layout": "quote",
        "title": "",
        "quote": {"text": " ", "attribution": "X"},
        "refs": ["S1:P1"],
    }

    out = run([title_slide(), good, empty, bullets_slide(1), summary_slide()])

    assert layouts(out) == ["title", "quote", "bullets", "summary"]
    assert out.content["slides"][1]["quote"] == {
        "text": "Light!",
        "attribution": "Teacher",
    }
    assert out.content["slides"][1]["title"] == ""


def test_table_rows_are_padded_and_cut_to_the_column_width() -> None:
    """NB-19: equal row widths."""
    table = {
        "columns": ["Stage", "Where"],
        "rows": [["Light"], ["Calvin", "Stroma", "extra"], ["", ""]],
    }
    slide = {"layout": "table", "title": "Table", "table": table, "refs": []}

    out = run([title_slide(), slide, summary_slide()])

    stored = out.content["slides"][1]["table"]
    assert stored["columns"] == ["Stage", "Where"]
    assert stored["rows"] == [["Light", ""], ["Calvin", "Stroma"]]


@pytest.mark.parametrize(
    "table",
    [
        None,
        {"columns": [], "rows": [["a"]]},
        {"columns": ["A"], "rows": []},
        {"columns": ["A"], "rows": [[""]]},
    ],
)
def test_a_table_slide_without_columns_or_rows_is_dropped(table: Any) -> None:
    """NB-19: the table needs columns and at least one row."""
    slide = {"layout": "table", "title": "Table", "table": table, "refs": []}

    out = run([title_slide(), bullets_slide(1), slide, summary_slide()])

    assert "table" not in layouts(out)


def test_presenter_bullets_have_hard_caps_of_seven_of_twenty_words() -> None:
    """NB-19: presenter: the prompt asks 5 x 12; the caps above it keep a slightly
    long bullet whole and cut only runaway text."""
    long = " ".join(f"w{i}" for i in range(30))
    slide = bullets_slide(1, bullets=[long] + [f"point {i}" for i in range(9)])

    out = run([title_slide(), slide, summary_slide()], format="presenter")

    bullets = out.content["slides"][1]["bullets"]
    assert len(bullets) == 7
    assert len(bullets[0].split()) == 20
    assert bullets[0].endswith("…")


def test_a_bullet_slightly_over_the_prompt_budget_is_kept_whole() -> None:
    """NB-19: 14 words in a presenter deck are not cut mid-sentence."""
    sentence = (
        "Хлорофилл поглощает красный и синий свет, а зелёный свет отражает обратно."
    )
    slide = bullets_slide(1, bullets=[sentence])

    out = run([title_slide(), slide, summary_slide()], format="presenter")

    assert out.content["slides"][1]["bullets"] == [sentence]


def test_detailed_bullets_have_hard_caps_of_eight_of_thirty_two_words() -> None:
    """NB-19: detailed limits, and the body is kept."""
    long = " ".join(f"w{i}" for i in range(60))
    slide = bullets_slide(
        1, bullets=[long] + [f"point {i}" for i in range(12)], body="A paragraph."
    )

    out = run([title_slide(), slide, summary_slide()], format="detailed")

    stored = out.content["slides"][1]
    assert len(stored["bullets"]) == 8
    assert len(stored["bullets"][0].split()) == 32
    assert stored["body"] == "A paragraph."


def test_empty_bullets_are_removed() -> None:
    """NB-19: blank bullets do not count."""
    slide = bullets_slide(1, bullets=["", "  ", "Real"])

    out = run([title_slide(), slide, summary_slide()])

    assert out.content["slides"][1]["bullets"] == ["Real"]


def test_a_bullets_slide_without_bullets_and_body_is_dropped() -> None:
    """NB-19: a bullets slide needs content."""
    empty = bullets_slide(1, bullets=[], body=None)

    out = run([title_slide(), empty, bullets_slide(2), summary_slide()])

    assert len(out.content["slides"]) == 3


def test_a_bullets_slide_without_a_title_is_dropped() -> None:
    """NB-19: only title/summary/quote slides may lack a title."""
    out = run(
        [title_slide(), bullets_slide(1, title=" "), bullets_slide(2), summary_slide()]
    )

    assert len(out.content["slides"]) == 3


def test_title_and_summary_slides_take_the_deck_title_when_untitled() -> None:
    """NB-19: an empty title on those layouts is repaired."""
    out = run([title_slide(title=""), bullets_slide(1), summary_slide(title="")])

    assert out.content["slides"][0]["title"] == "Photosynthesis"
    assert out.content["slides"][2]["title"] == "Photosynthesis"


@pytest.mark.parametrize(
    ("language", "title", "expected"),
    [
        ("uz", "Agenda", "Reja"),
        ("ru", "agenda", "План"),
        ("en", "План", "Agenda"),
        ("uz", "", "Reja"),
        ("en", "Lesson plan", "Lesson plan"),
        ("ru", "План урока", "План урока"),
    ],
)
def test_an_agenda_titled_in_another_language_takes_the_word_of_the_deck(
    language: str, title: str, expected: str
) -> None:
    """The model sometimes writes "Agenda" in an Uzbek or Russian deck."""
    agenda = {
        "id": "a",
        "layout": "agenda",
        "title": title,
        "bullets": ["Light reactions", "Calvin cycle"],
        "notes": "",
        "refs": [],
    }
    slides = [title_slide(), agenda, bullets_slide(1), summary_slide()]
    document = {"title": "Photosynthesis", "subtitle": None, "slides": slides}
    ctx = ProcessContext(pack=two_source_pack(), language=language, seed=1)

    out = HANDLER.process(document, HANDLER.parse_options({}), ctx)

    assert out.content["slides"][1]["title"] == expected


def test_visual_hint_loses_web_addresses() -> None:
    """NB-19: a hint is text only, never a URL."""
    slide = bullets_slide(
        1, visual_hint="Diagram, see https://evil.example/x.png and www.a.b/c"
    )

    out = run([title_slide(), slide, summary_slide()])

    assert out.content["slides"][1]["visual_hint"] == "Diagram, see and"


def test_a_hint_that_is_only_a_url_is_omitted() -> None:
    """NB-19: nothing is left of the hint."""
    slide = bullets_slide(1, visual_hint="https://example.com/pic.png")

    out = run([title_slide(), slide, summary_slide()])

    assert "visual_hint" not in out.content["slides"][1]


def test_notes_are_kept_and_capped() -> None:
    """NB-19: notes stay; absurd lengths are cut."""
    slide = bullets_slide(1, notes="n" * 5000)

    out = run([title_slide(), slide, summary_slide()])

    assert out.content["slides"][0]["notes"] == "Welcome"
    assert len(out.content["slides"][1]["notes"]) <= 1200


def test_fields_of_other_layouts_are_dropped() -> None:
    """NB-19: a bullets slide does not keep left/right/table/quote."""
    side = {"heading": "x", "bullets": ["y"]}
    slide = bullets_slide(
        1,
        left=side,
        right=side,
        quote={"text": "q"},
        table={"columns": ["a"], "rows": [["b"]]},
    )

    out = run([title_slide(), slide, summary_slide()])

    stored = out.content["slides"][1]
    assert not {"left", "right", "quote", "table"} & set(stored)


def test_slides_must_be_a_list() -> None:
    """NB-19: a document without slides is invalid."""
    with pytest.raises(OutputInvalidError):
        HANDLER.process(
            {"title": "x", "slides": "nope"}, HANDLER.parse_options({}), CTX
        )


def test_the_doc_example_deck_is_accepted() -> None:
    """NB-19: the example of § 3.4.6 passes with its five layouts."""
    side = {"heading": "Light reactions", "bullets": ["…"]}
    slides: list[dict[str, Any]] = [
        {
            "id": "s1",
            "layout": "title",
            "title": "Photosynthesis",
            "bullets": [],
            "notes": "Welcome...",
            "refs": [],
        },
        {
            "id": "s2",
            "layout": "bullets",
            "title": "Two stages",
            "bullets": ["Light reactions", "Calvin cycle"],
            "notes": "…",
            "visual_hint": "Two-box diagram",
            "refs": ["S1:P2"],
        },
        {
            "id": "s3",
            "layout": "two_columns",
            "title": "Compare",
            "left": side,
            "right": {**side, "heading": "Calvin cycle"},
            "refs": ["S1:P3", "S1:P5"],
        },
        {
            "id": "s4",
            "layout": "quote",
            "title": "",
            "quote": {"text": "…", "attribution": "Source title"},
            "refs": ["S1:P1"],
        },
        {
            "id": "s5",
            "layout": "table",
            "title": "Summary table",
            "table": {"columns": ["Stage", "Where"], "rows": [["Light", "Thylakoid"]]},
            "refs": [],
        },
    ]

    out = run(slides, length="short")

    assert layouts(out) == ["title", "bullets", "two_columns", "quote", "table"]
    assert out.content["slides"][2]["refs"] == ["S1:P3"]
