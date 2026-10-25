"""NB-14, NB-18: the data table kind (§ 3.4.5): options, columns, rows, refs."""

from typing import Any

from app.modules.notebooks.domain.artifacts.handler import (
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kinds.data_table import HANDLER
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from tests.notebooks.unit.domain.kinds_b_pack import two_source_pack

import pytest

CTX = ProcessContext(pack=two_source_pack(), language="en", seed=1)
YEAR = {"key": "year", "label": "Year", "type": "number"}
EVENT = {"key": "event", "label": "Event", "type": "text"}


def row(year: str, event: str, refs: list[str] | None = None) -> dict[str, Any]:
    """A row in the doc's form: ``cells`` is an object."""
    return {
        "cells": {"year": year, "event": event},
        "refs": ["S1:P1"] if refs is None else refs,
    }


def run(
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    **options: Any,
) -> ProcessedOutput:
    document = {"title": "Events", "columns": columns, "rows": rows}
    return HANDLER.process(document, HANDLER.parse_options(options), CTX)


def test_max_rows_defaults_to_twenty_five() -> None:
    """NB-14: default 25 rows."""
    assert HANDLER.stored_options(HANDLER.parse_options({})) == {"max_rows": 25}


@pytest.mark.parametrize("value", [9, 41, "many", 0])
def test_max_rows_outside_ten_to_forty_is_invalid(value: Any) -> None:
    """NB-14: 10 to 40."""
    with pytest.raises(InvalidOptionsError):
        HANDLER.parse_options({"max_rows": value})


@pytest.mark.parametrize("value", [10, 40])
def test_max_rows_bounds_are_accepted(value: int) -> None:
    """NB-14: both bounds are valid."""
    stored = HANDLER.stored_options(HANDLER.parse_options({"max_rows": value}))

    assert stored["max_rows"] == value


def test_handler_constants() -> None:
    """NB-14: token budget, schema name, no report format, input cap."""
    options = HANDLER.parse_options({})

    assert HANDLER.max_tokens(options) == 5000
    assert HANDLER.schema_name == "nb_data_table"
    assert HANDLER.kind.value == "data_table"
    assert HANDLER.report_format(options) is None
    assert HANDLER.input_cap_tokens(150_000) == 150_000
    assert HANDLER.default_title("Biology", options) == "Data table: Biology"


def test_task_block_names_the_row_cap_and_the_focus_prompt() -> None:
    """NB-18: the focus names the columns; the cap is in the text."""
    options = HANDLER.parse_options({"max_rows": 12})

    task = HANDLER.task_block(options, "date, place, people")

    assert "At most 12 rows" in task
    assert "date, place, people" in task
    assert "lowercase ASCII" in task
    assert "at most 120 characters" in task


def test_columns_and_rows_are_stored_as_in_the_contract() -> None:
    """NB-18: DataTableContent of § 4.4."""
    out = run([YEAR, EVENT], [row("1873", "Protectorate")])

    assert out.content["columns"] == [YEAR, EVENT]
    assert out.content["rows"] == [
        {"cells": {"year": "1873", "event": "Protectorate"}, "refs": ["S1:P1"]}
    ]
    assert out.title == "Events"


def test_keys_are_normalised_to_lowercase_ascii() -> None:
    """NB-18: keys are lowercase ASCII; cells follow the model's original key."""
    columns = [{"key": "Year of Event", "label": "Year", "type": "date"}, EVENT]
    rows = [{"cells": {"Year of Event": "1873", "event": "x"}, "refs": ["S1:P1"]}]

    out = run(columns, rows)

    assert out.content["columns"][0]["key"] == "year_of_event"
    assert out.content["rows"][0]["cells"]["year_of_event"] == "1873"


def test_non_latin_keys_get_a_positional_key() -> None:
    """NB-18: a key without any ASCII letter becomes col<N>."""
    columns = [{"key": "Год", "label": "Год", "type": "number"}, EVENT]
    rows = [{"cells": {"Год": "1873", "event": "x"}, "refs": ["S1:P1"]}]

    out = run(columns, rows)

    assert out.content["columns"][0]["key"] == "col1"
    assert out.content["rows"][0]["cells"] == {"col1": "1873", "event": "x"}


def test_duplicate_keys_are_made_unique() -> None:
    """NB-18: unique keys; the first column keeps the plain key."""
    columns = [YEAR, {**YEAR, "label": "Year again"}, EVENT]

    out = run(columns, [row("1873", "x")])

    keys = [c["key"] for c in out.content["columns"]]
    assert keys == ["year", "year_2", "event"]
    assert out.content["rows"][0]["cells"]["year"] == "1873"
    assert out.content["rows"][0]["cells"]["year_2"] == ""


def test_more_than_eight_columns_are_trimmed_to_eight() -> None:
    """NB-18: 1 to 8 columns."""
    columns = [{"key": f"c{i}", "label": f"C{i}", "type": "text"} for i in range(11)]

    out = run(columns, [{"cells": {"c0": "a", "c10": "z"}, "refs": ["S1:P1"]}])

    assert len(out.content["columns"]) == 8
    assert "c10" not in out.content["rows"][0]["cells"]


def test_long_labels_are_cut_to_sixty_characters() -> None:
    """NB-18: label <= 60."""
    columns = [{"key": "year", "label": "L" * 100, "type": "text"}]

    out = run(columns, [{"cells": {"year": "1"}, "refs": ["S1:P1"]}])

    assert len(out.content["columns"][0]["label"]) <= 60


def test_an_empty_label_falls_back_to_the_key() -> None:
    """NB-18: a column always has a label."""
    out = run([{"key": "year", "label": " ", "type": "text"}], [row("1", "x")])

    assert out.content["columns"][0]["label"] == "year"


def test_a_column_with_an_unknown_type_is_dropped() -> None:
    """NB-18: type is text, number or date."""
    columns = [{"key": "tag", "label": "Tag", "type": "emoji"}, EVENT]

    out = run(columns, [row("1873", "x")])

    assert [c["key"] for c in out.content["columns"]] == ["event"]


def test_no_columns_is_an_invalid_output() -> None:
    """NB-18: no columns -> OutputInvalidError."""
    with pytest.raises(OutputInvalidError):
        run([], [row("1", "x")])


def test_missing_cells_are_filled_and_unknown_keys_dropped() -> None:
    """NB-18: missing cell -> empty string; unknown key -> dropped."""
    rows = [{"cells": {"event": "x", "colour": "red"}, "refs": ["S1:P1"]}]

    out = run([YEAR, EVENT], rows)

    assert out.content["rows"][0]["cells"] == {"year": "", "event": "x"}


def test_cells_are_cut_to_one_hundred_twenty_characters() -> None:
    """NB-18: cells <= 120 characters."""
    out = run([YEAR, EVENT], [row("1", "e" * 400)])

    assert len(out.content["rows"][0]["cells"]["event"]) <= 120


def test_numbers_and_dates_are_not_reformatted() -> None:
    """NB-18: values stay as written (only whitespace is collapsed)."""
    columns = [YEAR, {"key": "day", "label": "Day", "type": "date"}]
    rows = [{"cells": {"year": "1 873,50", "day": "12  May\n1873"}, "refs": ["S1:P1"]}]

    out = run(columns, rows)

    assert out.content["rows"][0]["cells"] == {"year": "1 873,50", "day": "12 May 1873"}


def test_numeric_cell_values_become_text() -> None:
    """NB-18: a model that writes 1873 instead of "1873" is accepted."""
    rows = [{"cells": {"year": 1873, "event": "x"}, "refs": ["S1:P1"]}]

    out = run([YEAR, EVENT], rows)

    assert out.content["rows"][0]["cells"]["year"] == "1873"


def test_cells_as_key_value_pairs_are_accepted() -> None:
    """NB-18: the strict schema writes cells as [{key, value}]."""
    pairs = [{"key": "year", "value": "1873"}, {"key": "event", "value": "x"}]

    out = run([YEAR, EVENT], [{"cells": pairs, "refs": ["S1:P2"]}])

    assert out.content["rows"][0] == {
        "cells": {"year": "1873", "event": "x"},
        "refs": ["S1:P2"],
    }


def test_rows_beyond_the_cap_are_cut() -> None:
    """NB-18: rows <= max_rows."""
    rows = [row(str(1800 + i), f"event {i}") for i in range(30)]

    out = run([YEAR, EVENT], rows, max_rows=10)

    assert len(out.content["rows"]) == 10
    assert out.content["rows"][0]["cells"]["year"] == "1800"


def test_rows_without_text_are_dropped() -> None:
    """NB-18: a row of empty cells is not a row."""
    out = run([YEAR, EVENT], [row("", ""), row("1873", "x")])

    assert len(out.content["rows"]) == 1


def test_no_rows_is_an_invalid_output() -> None:
    """NB-18: no rows -> OutputInvalidError."""
    with pytest.raises(OutputInvalidError):
        run([YEAR, EVENT], [])


def test_rows_without_valid_refs_are_dropped_when_most_rows_have_them() -> None:
    """NB-18: keep_items_with_refs drops the unsupported rows."""
    rows = [row("1", "a"), row("2", "b"), row("3", "c", refs=["S7:P7"])]

    out = run([YEAR, EVENT], rows)

    assert [r["cells"]["year"] for r in out.content["rows"]] == ["1", "2"]


def test_rows_without_refs_are_honest_and_kept_while_invented_ones_go() -> None:
    """NB-18: [] means own knowledge (kept); an invented label is dropped."""
    rows = [row("1", "a"), row("2", "b", refs=[]), row("3", "c", refs=["S7:P7"])]

    out = run([YEAR, EVENT], rows)

    assert [r["cells"]["year"] for r in out.content["rows"]] == ["1", "2"]
    assert out.content["rows"][1]["refs"] == []


def test_rows_are_kept_when_less_than_half_are_trusted() -> None:
    """NB-18: thin sources keep every row."""
    rows = [row("1", "a"), row("2", "b", refs=["S8:P8"]), row("3", "c", refs=["S7:P7"])]

    out = run([YEAR, EVENT], rows)

    assert len(out.content["rows"]) == 3
    assert out.content["rows"][2]["refs"] == []


def test_refs_index_covers_every_used_label() -> None:
    """NB-18: refs resolved once into the artifact-level index."""
    rows = [row("1", "a", refs=["S1:P1", "S2:P3"]), row("2", "b", refs=["S2:P3"])]

    out = run([YEAR, EVENT], rows)

    assert set(out.refs_index) == {"S1:P1", "S2:P3"}
    assert out.refs_index["S1:P1"]["page"] == 1
    assert out.refs_index["S2:P3"]["source_title"] == "Lesson notes"


def test_broken_rows_are_reported_in_the_problems() -> None:
    """NB-18: the repair call learns why the table is empty."""
    with pytest.raises(OutputInvalidError) as caught:
        run([YEAR, EVENT], [{"nope": 1}, {"cells": {"colour": "red"}, "refs": []}])

    assert any(p.startswith("row 1") for p in caught.value.problems)
    assert any(p.startswith("row 2") for p in caught.value.problems)


@pytest.mark.parametrize("bad", [None, {"a": 1}, "x"])
def test_rows_and_columns_must_be_lists(bad: Any) -> None:
    """NB-18: a document without lists is invalid."""
    options = HANDLER.parse_options({})

    with pytest.raises(OutputInvalidError):
        HANDLER.process({"title": "x", "columns": bad, "rows": []}, options, CTX)
    with pytest.raises(OutputInvalidError):
        HANDLER.process({"title": "x", "columns": [YEAR], "rows": bad}, options, CTX)
