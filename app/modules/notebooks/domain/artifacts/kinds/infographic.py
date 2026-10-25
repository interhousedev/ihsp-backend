"""Infographic (§ 3.4.7): 5 to 9 short blocks; the layout is left to the renderer."""

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

from pydantic import BaseModel

BlockType = Literal[
    "stat", "steps", "comparison", "list", "timeline", "definition", "quote", "callout"
]
Orientation = Literal["portrait", "landscape", "square"]
Detail = Literal["concise", "standard", "detailed"]
Style = Literal["clean", "sketch", "bento", "scientific", "playful"]

MAX_TOKENS: Final = 3_500
INPUT_CAP_TOKENS: Final = 100_000
MIN_BLOCKS: Final = 3
BLOCK_COUNTS: Final = {"concise": (5, 5), "standard": (6, 7), "detailed": (8, 9)}
TITLE_WORDS: Final = 6
BODY_WORDS: Final = 18
TITLE_CHARS: Final = 80
BODY_CHARS: Final = 200
EDGE_CHARS: Final = 120
MAX_ITEMS: Final = {
    "stat": 4,
    "steps": 7,
    "list": 8,
    "timeline": 8,
    "definition": 4,
    "quote": 1,
    "callout": 1,
    "comparison": 4,
}
MAX_COLUMNS: Final = 3
MAX_POINTS: Final = 6
MIN_COLUMNS: Final = 2


class InfographicOptions(CommonOptions):
    """`InfographicOptions` of § 4.4 with the defaults filled."""

    orientation: Orientation = "portrait"
    detail: Detail = "standard"
    style: Style = "clean"


class ItemOut(BaseModel):
    """A head and a body (value and caption, step, date and event, term...)."""

    head: str | None = None
    body: str | None = None


class ColumnOut(BaseModel):
    """A column of a comparison."""

    title: str | None = None
    points: list[str] | None = None


class BlockOut(BaseModel):
    """A block as the model writes it (`InfographicBlock` of § 4.4)."""

    type: BlockType
    title: str | None = None
    items: list[ItemOut] | None = None
    columns: list[ColumnOut] | None = None
    refs: list[str] | None = None


class InfographicOut(BaseModel):
    """The model's JSON document."""

    title: str
    subtitle: str | None = None
    footer: str | None = None
    blocks: list[BlockOut]


@dataclass(slots=True)
class _Block:
    type: str
    title: str
    items: list[dict[str, str]]
    columns: list[dict[str, Any]] | None
    refs: list[str]
    trusted: bool = True  # valid refs, or honestly none (see `cites_honestly`)

    def stored(self) -> dict[str, Any]:
        """The block as stored: `columns` only on comparisons."""
        block: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "items": self.items,
        }
        if self.columns is not None:
            block["columns"] = self.columns
        block["refs"] = self.refs
        return block


def _items(raw: list[ItemOut] | None, kind: str) -> list[dict[str, str]]:
    """Items with a head or a body, texts trimmed, capped by block type."""
    items = [
        {
            "head": fit_text(i.head, words=TITLE_WORDS, chars=TITLE_CHARS),
            "body": fit_text(i.body, words=BODY_WORDS, chars=BODY_CHARS),
        }
        for i in raw or []
    ]
    return [i for i in items if i["head"] or i["body"]][: MAX_ITEMS[kind]]


def _columns(raw: list[ColumnOut] | None) -> list[dict[str, Any]]:
    """Comparison columns with a title or points (two or three of them)."""
    columns = []
    for column in raw or []:
        points = [
            fit_text(p, words=BODY_WORDS, chars=BODY_CHARS) for p in column.points or []
        ]
        title = fit_text(column.title, words=TITLE_WORDS, chars=TITLE_CHARS)
        points = [p for p in points if p][:MAX_POINTS]
        if title or points:
            columns.append({"title": title, "points": points})
    return columns[:MAX_COLUMNS]


def _block(raw: BlockOut) -> _Block | None:
    """Repair one block; None when it has nothing to show."""
    title = fit_text(raw.title, words=TITLE_WORDS, chars=TITLE_CHARS)
    items = _items(raw.items, raw.type)
    if raw.type != "comparison":
        if not items:
            return None
        return _Block(raw.type, title, items, None, list(raw.refs or []))
    columns = _columns(raw.columns)
    if len(columns) < MIN_COLUMNS:
        return None
    return _Block(raw.type, title, items, columns, list(raw.refs or []))


def _blocks(parsed: list[tuple[int, BlockOut]], problems: list[str]) -> list[_Block]:
    """The blocks that have something to show; the others are reported."""
    blocks = []
    for number, raw in parsed:
        block = _block(raw)
        if block is None:
            problems.append(f"block {number}: {raw.type} has no usable items")
        else:
            blocks.append(block)
    return blocks


class InfographicHandler:
    """Options, prompt, schema and validation of the infographic kind."""

    kind: ArtifactKind = ArtifactKind.INFOGRAPHIC
    schema_name: str = "nb_infographic"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(InfographicOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, InfographicOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """An infographic has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """3 500."""
        return MAX_TOKENS

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio cap, but never above 100 000 tokens."""
        return min(studio_context_tokens, INPUT_CAP_TOKENS)

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `InfographicOut`."""
        return to_strict_schema(InfographicOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (§ 3.4.7) for the last user message."""
        opts = expect_options(options, InfographicOptions)
        low, high = BLOCK_COUNTS[opts.detail]
        count = str(low) if low == high else f"{low} to {high}"
        return (
            "Create an infographic that summarizes the sources visually. Choose "
            f"{count} blocks in a logical order. Block types: `stat` (big number or "
            "term with a caption), `steps` (ordered process), `comparison` (two or "
            "three columns), `list`, `timeline`, `definition`, `quote`, `callout` "
            "(one key takeaway). Every block has `items` of {head, body}; a "
            "`comparison` also has `columns` of {title, points}. Keep every text "
            f"short: titles at most {TITLE_WORDS} words, bodies at most "
            f"{BODY_WORDS} words. Leave the layout to the renderer."
            f"{focus_clause(prompt)}"
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Infographic: <notebook>``."""
        return f"Infographic: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Drop unusable blocks, trim texts, resolve refs and cap the block count."""
        opts = expect_options(options, InfographicOptions)
        problems: list[str] = []
        parsed = validate_numbered(
            BlockOut, require_list(data, "blocks"), problems, "block"
        )
        blocks = _blocks(parsed, problems)
        for block in blocks:
            raw = block.refs
            block.refs = valid_refs(raw, ctx.pack)
            block.trusted = cites_honestly(raw, block.refs)
        wanted = BLOCK_COUNTS[opts.detail][1]
        kept = keep_items_with_refs(blocks, lambda b: b.trusted, wanted)[:wanted]
        if len(kept) < MIN_BLOCKS:
            raise OutputInvalidError(problems or [f"fewer than {MIN_BLOCKS} blocks"])
        title = document_title(data, ctx.pack, "Infographic")
        content = {
            "title": title,
            "subtitle": fit_text(data.get("subtitle"), chars=EDGE_CHARS) or None,
            "footer": fit_text(data.get("footer"), chars=EDGE_CHARS) or None,
            "blocks": [b.stored() for b in kept],
        }
        return ProcessedOutput(
            title=title,
            content=content,
            refs_index=build_refs_index((b.refs for b in kept), ctx.pack),
        )


HANDLER: ArtifactHandler = InfographicHandler()
