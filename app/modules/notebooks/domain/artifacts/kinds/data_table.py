"""Data table (§ 3.4.5): columns and rows extracted from the sources.

The model writes the cells of a row as a list of ``{key, value}`` pairs, because a
strict schema cannot describe an object with dynamic keys. The stored content has
the shape of § 4.4 (``cells`` is an object), and the plain object form of the doc
is accepted too.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    document_title,
    dump_options,
    expect_options,
    fit_text,
    parse_options,
    require_list,
    validate_items,
    validate_numbered,
)
from app.modules.notebooks.domain.artifacts.refs import (
    build_refs_index,
    cites_honestly,
    keep_items_with_refs,
    valid_refs,
)
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.common import focus_clause

from pydantic import BaseModel, Field

MAX_TOKENS: Final = 5_000
MAX_COLUMNS: Final = 8
LABEL_CHARS: Final = 60
CELL_CHARS: Final = 120
KEY_CHARS: Final = 30
_NOT_KEY = re.compile(r"[^a-z0-9]+")


class DataTableOptions(CommonOptions):
    """`DataTableOptions` of § 4.4: the row cap (the focus prompt names columns)."""

    max_rows: int = Field(default=25, ge=10, le=40)


class ColumnOut(BaseModel):
    """A column as the model writes it."""

    key: str
    label: str
    type: Literal["text", "number", "date"]


class CellOut(BaseModel):
    """One cell: the column key and the text."""

    key: str
    value: str


class RowOut(BaseModel):
    """A row as the model writes it."""

    cells: list[CellOut]
    refs: list[str] | None = None


class DataTableOut(BaseModel):
    """The model's JSON document."""

    title: str
    columns: list[ColumnOut]
    rows: list[RowOut]


@dataclass(slots=True)
class _Row:
    cells: dict[str, str]
    refs: list[str]
    trusted: bool = True  # valid refs, or honestly none (see `cites_honestly`)


def ascii_key(raw: str) -> str:
    """Lowercase ASCII letters, digits and underscores (``""`` if nothing is left)."""
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return _NOT_KEY.sub("_", folded.lower()).strip("_")[:KEY_CHARS]


def _unique_key(key: str, used: set[str]) -> str:
    """Add ``_2``, ``_3`` ... until the key is unused."""
    candidate, counter = key, 1
    while candidate in used:
        counter += 1
        candidate = f"{key}_{counter}"
    return candidate


def _columns(
    raw: list[Any], problems: list[str]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Normalised columns (at most 8) and a map from the model's keys to ours."""
    columns: list[dict[str, str]] = []
    key_map: dict[str, str] = {}
    used: set[str] = set()
    for column in validate_items(ColumnOut, raw, problems, "column"):
        if len(columns) >= MAX_COLUMNS:
            break
        base = ascii_key(column.key) or f"col{len(columns) + 1}"
        key = _unique_key(base, used)
        used.add(key)
        label = fit_text(column.label, chars=LABEL_CHARS) or key
        columns.append({"key": key, "label": label, "type": column.type})
        for source in (column.key, ascii_key(column.key)):
            if source:
                key_map.setdefault(source, key)
    return columns, key_map


def _cell_text(value: object) -> str:
    """Scalar cell values become text; nothing else is a cell."""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return ""


def _as_pairs(raw: Any) -> Any:
    """Accept ``cells`` as the doc's object or as a list of pairs."""
    if not isinstance(raw, dict):
        return raw
    cells = raw.get("cells")
    if isinstance(cells, dict):
        pairs = [{"key": str(k), "value": _cell_text(v)} for k, v in cells.items()]
        return {**raw, "cells": pairs}
    if isinstance(cells, list):
        fixed = [
            {**pair, "value": _cell_text(pair.get("value"))}
            for pair in cells
            if isinstance(pair, dict)
        ]
        return {**raw, "cells": fixed}
    return raw


def _row(
    item: RowOut, columns: list[dict[str, str]], key_map: dict[str, str]
) -> _Row | None:
    """Fill the cells by column; missing ones are ``""``, unknown keys are dropped."""
    cells = {column["key"]: "" for column in columns}
    for cell in item.cells:
        key = key_map.get(cell.key) or key_map.get(ascii_key(cell.key))
        if key is not None and not cells[key]:
            cells[key] = fit_text(cell.value, chars=CELL_CHARS)
    if not any(cells.values()):
        return None
    return _Row(cells=cells, refs=list(item.refs or []))


def _rows(
    parsed: list[tuple[int, RowOut]],
    columns: list[dict[str, str]],
    key_map: dict[str, str],
    problems: list[str],
) -> list[_Row]:
    """The rows that have at least one cell; empty ones are reported."""
    rows = []
    for number, item in parsed:
        row = _row(item, columns, key_map)
        if row is None:
            problems.append(f"row {number}: no cell has text for a known column")
        else:
            rows.append(row)
    return rows


class DataTableHandler:
    """Options, prompt, schema and validation of the data table kind."""

    kind: ArtifactKind = ArtifactKind.DATA_TABLE
    schema_name: str = "nb_data_table"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(DataTableOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, DataTableOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """A data table has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """5 000."""
        return MAX_TOKENS

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `DataTableOut`."""
        return to_strict_schema(DataTableOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (§ 3.4.5) for the last user message."""
        opts = expect_options(options, DataTableOptions)
        return (
            "Extract a table from the sources. If the focus prompt names columns, "
            "use exactly those columns (keys are lowercase ASCII, labels in the "
            "output language). Otherwise choose the most useful 3 to 6 columns, for "
            f"example term, definition, example. At most {opts.max_rows} rows, one "
            f"entity per row. Every cell is a short text (at most {CELL_CHARS} "
            "characters); use an empty string when the sources do not say. `type` "
            "is `text`, `number` or `date`. Write the cells of a row as a list of "
            "objects {key, value}, one per column."
            f"{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Data table: <notebook>``."""
        return f"Data table: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Normalise columns, fill cells, resolve refs and apply the row cap."""
        opts = expect_options(options, DataTableOptions)
        problems: list[str] = []
        columns, key_map = _columns(require_list(data, "columns"), problems)
        if not columns:
            raise OutputInvalidError(problems or ["no columns"])
        raw_rows = [_as_pairs(row) for row in require_list(data, "rows")]
        parsed = validate_numbered(RowOut, raw_rows, problems, "row")
        rows = _rows(parsed, columns, key_map, problems)
        for row in rows:
            raw = row.refs
            row.refs = valid_refs(raw, ctx.pack)
            row.trusted = cites_honestly(raw, row.refs)
        kept = keep_items_with_refs(rows, lambda r: r.trusted, len(rows))
        kept = kept[: opts.max_rows]
        if not kept:
            raise OutputInvalidError(problems or ["no rows"])
        stored = [{"cells": r.cells, "refs": r.refs} for r in kept]
        title = document_title(data, ctx.pack, "Data table")
        return ProcessedOutput(
            title=title,
            content={"title": title, "columns": columns, "rows": stored},
            refs_index=build_refs_index((r.refs for r in kept), ctx.pack),
        )


HANDLER: ArtifactHandler = DataTableHandler()
