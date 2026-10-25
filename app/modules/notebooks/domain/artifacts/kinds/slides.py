"""Slide deck (§ 3.4.6): a title slide, an agenda, content slides, a summary.

`repair_slide` is the one place that knows what a valid slide of each layout looks
like; generation, the student's edits (`slides_edit`) and revisions
(`prompts.slides_revise`) all go through it. The outline rules of a whole deck are in
`slides_shape`, the plain-text cleaning in `slide_text`, the task text in
`prompts.slides_task`.
"""

from collections.abc import Callable
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
    parse_options,
    require_list,
    strip_urls,
    validate_numbered,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index, valid_refs
from app.modules.notebooks.domain.artifacts.slide_outline import (
    PlanSlide,
    outline_clause,
)
from app.modules.notebooks.domain.artifacts.slide_text import inline_labels, slide_text
from app.modules.notebooks.domain.artifacts.slides_shape import (
    TOLERANCE,
    content_count,
    drop_repeats,
    shape_deck,
    uncited,
)
from app.modules.notebooks.domain.artifacts.strict import NOT_NULL, to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.slides_task import SlideFormat, slides_task

from pydantic import BaseModel, Field

Layout = Literal[
    "title",
    "agenda",
    "section",
    "bullets",
    "two_columns",
    "quote",
    "table",
    "summary",
]
Length = Literal["short", "default", "long"]

SLIDE_COUNTS: Final = {"short": 6, "default": 10, "long": 16}
MAX_TOKENS: Final = {"short": 4_000, "default": 7_000, "long": 11_000}
SLIDE_TOLERANCE: Final = TOLERANCE
MIN_SLIDES: Final = 3
MIN_AGENDA_ITEMS: Final = 2
TITLE_CHARS: Final = 120
NOTES_CHARS: Final = 1_200
HINT_CHARS: Final = 200
QUOTE_CHARS: Final = 400
ATTRIBUTION_CHARS: Final = 120
HEADING_CHARS: Final = 60
BULLET_CHARS: Final = 300
TABLE_COLUMNS: Final = 6
TABLE_ROWS: Final = 10
TABLE_CELL_CHARS: Final = 80
COLUMN_BULLETS: Final = 6
AGENDA_TITLES: Final = {"uz": "Reja", "ru": "План", "en": "Agenda"}
_AGENDA_WORDS: Final = frozenset(word.casefold() for word in AGENDA_TITLES.values())


@dataclass(frozen=True, slots=True)
class BulletLimits:
    """The hard caps of a slide's text (the prompt asks for less, see `GUIDES`).

    The caps sit above what the task block asks for, so a slightly long bullet is
    kept whole instead of being cut mid-sentence.
    """

    count: int
    words: int
    body_chars: int


BULLET_LIMITS: Final = {
    "presenter": BulletLimits(count=7, words=20, body_chars=600),
    "detailed": BulletLimits(count=8, words=32, body_chars=600),
}
# The student's own edits: generous caps, the viewer shrinks dense slides to fit.
EDIT_LIMITS: Final = BulletLimits(count=12, words=80, body_chars=1_200)


class SlidesOptions(CommonOptions):
    """`SlidesOptions` of § 4.4 with the defaults filled."""

    format: SlideFormat = "presenter"
    length: Length = "default"
    # A confirmed presentation plan (PLAN): the deck follows it slide by slide.
    outline: list[PlanSlide] | None = Field(
        None, max_length=SLIDE_COUNTS["long"] + TOLERANCE
    )


# The docstrings and descriptions of these models are shown to the model in the schema.
# `NOT_NULL` keeps the deck's schema under the provider's limit of nullable fields; the
# model writes "" or [] instead of null, which `_side` and `_quote` read the same way.


class ColumnOut(BaseModel):
    """One side of a two-column slide."""

    heading: str | None = Field(
        None, description="At most 4 words.", json_schema_extra=NOT_NULL
    )
    bullets: list[str] | None = Field(
        None, description="At most 4 short bullets.", json_schema_extra=NOT_NULL
    )


class QuoteOut(BaseModel):
    """A quotation with its attribution."""

    text: str = Field(description="A sentence copied word for word from a source.")
    attribution: str | None = Field(
        None,
        description='The author or source title, or "" if unknown.',
        json_schema_extra=NOT_NULL,
    )


class TableOut(BaseModel):
    """A small table."""

    columns: list[str] = Field(description="2 to 4 column headings.")
    rows: list[list[str]] = Field(description="At most 6 rows, one cell per column.")


class SlideOut(BaseModel):
    """A slide as the model writes it (`Slide` of § 4.4); also the edit format."""

    id: str | None = None
    layout: Layout = Field(description="Which fields the slide uses, see the task.")
    title: str | None = Field(None, description="One specific idea, at most 8 words.")
    bullets: list[str] | None = Field(
        None, description="Plain-text points: title, agenda, section, bullets, summary."
    )
    body: str | None = Field(None, description="One short paragraph or null.")
    left: ColumnOut | None = Field(None, description="two_columns only.")
    right: ColumnOut | None = Field(None, description="two_columns only.")
    quote: QuoteOut | None = Field(None, description="quote only.")
    table: TableOut | None = Field(None, description="table only.")
    notes: str | None = Field(None, description="Speaker notes.")
    visual_hint: str | None = Field(None, description="A picture idea, never a URL.")
    refs: list[str] | None = Field(
        None, description='1 to 3 labels from <sources>, e.g. "S1:P4".'
    )


class SlidesOut(BaseModel):
    """The model's JSON document."""

    title: str = Field(description="The topic of the deck, at most 8 words.")
    subtitle: str | None = Field(None, description="One line: subject or audience.")
    slides: list[SlideOut]


def slide_refs(slide: SlideOut) -> list[str]:
    """The slide's `refs` plus the labels it wrote as markers inside its texts."""
    texts: list[str | None] = [slide.title, slide.body, slide.notes]
    texts += slide.bullets or []
    for side in (slide.left, slide.right):
        texts += [side.heading, *(side.bullets or [])] if side else []
    if slide.quote:
        texts += [slide.quote.text, slide.quote.attribution]
    if slide.table:
        texts += [*slide.table.columns, *(c for row in slide.table.rows for c in row)]
    return [*(slide.refs or []), *inline_labels(texts)]


def _bullets(items: list[str] | None, limits: BulletLimits) -> list[str]:
    """Non-empty bullets, trimmed in words and capped in number."""
    texts = (
        slide_text(i, words=limits.words, chars=BULLET_CHARS, item=True)
        for i in items or []
    )
    return [text for text in texts if text][: limits.count]


def _flow(slide: SlideOut, limits: BulletLimits) -> dict[str, Any] | None:
    """Fields of the layouts that hold bullets and an optional body."""
    fields: dict[str, Any] = {"bullets": _bullets(slide.bullets, limits)}
    body = slide_text(slide.body, chars=limits.body_chars)
    if body:
        fields["body"] = body
    needs_text = slide.layout in ("bullets", "summary")
    if needs_text and not (fields["bullets"] or body):
        return None
    if slide.layout == "agenda" and len(fields["bullets"]) < MIN_AGENDA_ITEMS:
        return None
    return fields


def _side(side: ColumnOut | None, limits: BulletLimits) -> dict[str, Any] | None:
    """One column of a two-column slide; None when it has no content."""
    if side is None:
        return None
    bullets = _bullets(side.bullets, limits)[:COLUMN_BULLETS]
    heading = slide_text(side.heading, chars=HEADING_CHARS)
    if not (heading or bullets):
        return None
    return {"heading": heading, "bullets": bullets}


def _two_columns(slide: SlideOut, limits: BulletLimits) -> dict[str, Any] | None:
    """Both columns are required."""
    left, right = _side(slide.left, limits), _side(slide.right, limits)
    if left is None or right is None:
        return None
    return {"left": left, "right": right}


def _quote(slide: SlideOut, limits: BulletLimits) -> dict[str, Any] | None:
    """The quotation text is required, the attribution is optional."""
    if slide.quote is None:
        return None
    text = slide_text(slide.quote.text, chars=QUOTE_CHARS).strip("\"'«»“”„ ")
    if not text:
        return None
    attribution = slide_text(slide.quote.attribution, chars=ATTRIBUTION_CHARS)
    return {"quote": {"text": text, "attribution": attribution.lstrip("—–- ") or None}}


def _table(slide: SlideOut, limits: BulletLimits) -> dict[str, Any] | None:
    """Columns and rows are required; every row gets exactly one cell per column."""
    if slide.table is None:
        return None
    heads = [slide_text(c, chars=TABLE_CELL_CHARS) for c in slide.table.columns]
    heads = heads[:TABLE_COLUMNS]
    width = len(heads)
    rows = [
        [slide_text(c, chars=TABLE_CELL_CHARS) for c in row][:width]
        for row in slide.table.rows
    ]
    rows = [row + [""] * (width - len(row)) for row in rows if any(row)]
    if not any(heads) or not rows:
        return None
    return {"table": {"columns": heads, "rows": rows[:TABLE_ROWS]}}


_LAYOUTS: Final[
    dict[str, Callable[[SlideOut, BulletLimits], dict[str, Any] | None]]
] = {
    "title": _flow,
    "agenda": _flow,
    "section": _flow,
    "bullets": _flow,
    "summary": _flow,
    "two_columns": _two_columns,
    "quote": _quote,
    "table": _table,
}
_TITLE_FALLBACK: Final = frozenset({"title", "summary"})


def repair_slide(
    slide: SlideOut, limits: BulletLimits, deck_title: str = ""
) -> dict[str, Any] | None:
    """Return the slide without `id` and `refs`, repaired, or None if it cannot be.

    The layout's required fields are checked, extra fields of other layouts are
    dropped, texts lose Markdown and citation markers and are trimmed,
    `visual_hint` loses any web address. A title or summary slide without a title
    takes the deck's title.
    """
    title = slide_text(slide.title, chars=TITLE_CHARS)
    if title.endswith(".") and not title.endswith(".."):
        title = title[:-1]
    if slide.layout in _TITLE_FALLBACK:
        title = title or slide_text(deck_title, chars=TITLE_CHARS)
    if not title and slide.layout != "quote":
        return None
    fields = _LAYOUTS[slide.layout](slide, limits)
    if fields is None:
        return None
    repaired: dict[str, Any] = {"layout": slide.layout, "title": title, **fields}
    repaired["notes"] = slide_text(slide.notes, chars=NOTES_CHARS)
    hint = slide_text(strip_urls(slide.visual_hint or ""), chars=HINT_CHARS)
    if hint:
        repaired["visual_hint"] = hint
    return repaired


def _with_agenda_title(slide: SlideOut, language: str) -> SlideOut:
    """The word for "Agenda" of the deck's language on an untitled agenda.

    Also on one titled with that word of another language ("Agenda" in an Uzbek
    deck); an agenda with a title of its own ("Lesson plan") keeps it.
    """
    if slide.layout != "agenda":
        return slide
    word = AGENDA_TITLES.get(language, AGENDA_TITLES["en"])
    title = slide_text(slide.title)
    if title == word or (title and title.casefold() not in _AGENDA_WORDS):
        return slide
    return slide.model_copy(update={"title": word})


def _attributed(slide: dict[str, Any], ctx: ProcessContext) -> dict[str, Any]:
    """A quote without an attribution names the source of its first ref."""
    quote = slide.get("quote")
    if not quote or quote.get("attribution") or not slide["refs"]:
        return slide
    passage = ctx.pack.labels[slide["refs"][0]]
    title, _ = ctx.pack.titles[passage.source_id]
    return {**slide, "quote": {**quote, "attribution": title[:ATTRIBUTION_CHARS]}}


def _repair_all(
    slides: list[tuple[int, SlideOut]],
    limits: BulletLimits,
    deck_title: str,
    ctx: ProcessContext,
    problems: list[str],
) -> list[dict[str, Any]]:
    """Repair every slide; the unrepairable ones are dropped and reported.

    A quote slide must cite the passage it quotes, else it is dropped too.
    """
    repaired = []
    for number, raw in slides:
        slide = _with_agenda_title(raw, ctx.language)
        body = repair_slide(slide, limits, deck_title)
        if body is None:
            problems.append(f"slide {number}: layout {slide.layout} lacks its fields")
            continue
        refs = valid_refs(slide_refs(slide), ctx.pack)
        if slide.layout == "quote" and not refs:
            problems.append(f"slide {number}: a quote must cite the passage it quotes")
            continue
        repaired.append(_attributed({**body, "refs": refs}, ctx))
    return repaired


def _check_grounded(slides: list[dict[str, Any]], problems: list[str]) -> None:
    """A deck in which no content slide cites a passage is not grounded: repair it."""
    missing = uncited(slides)
    if content_count(slides) >= 2 and len(missing) == content_count(slides):
        numbers = ", ".join(str(n) for n in missing)
        raise OutputInvalidError(
            [
                f"slides {numbers}: no slide cites the sources; every content slide "
                'needs `refs` with 1 to 3 labels from <sources>, such as "S1:P2"',
                *problems,
            ]
        )


class SlidesHandler:
    """Options, prompt, schema and validation of the slide deck kind."""

    kind: ArtifactKind = ArtifactKind.SLIDES
    schema_name: str = "nb_slides"

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(SlidesOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, SlidesOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """A slide deck has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """4 000 / 7 000 / 11 000 for short / default / long."""
        return MAX_TOKENS[expect_options(options, SlidesOptions).length]

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `SlidesOut`."""
        return to_strict_schema(SlidesOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (§ 3.4.6) for the last user message."""
        opts = expect_options(options, SlidesOptions)
        task = slides_task(
            count=SLIDE_COUNTS[opts.length],
            tolerance=SLIDE_TOLERANCE,
            fmt=opts.format,
            prompt=prompt,
        )
        return task + outline_clause(opts.outline)

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Slides: <notebook>``."""
        return f"Slides: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Repair the slides, apply the outline rules, number them."""
        opts = expect_options(options, SlidesOptions)
        problems: list[str] = []
        deck_title = slide_text(document_title(data, ctx.pack, "Slides"))
        parsed = validate_numbered(
            SlideOut, require_list(data, "slides"), problems, "slide"
        )
        repaired = drop_repeats(
            _repair_all(parsed, BULLET_LIMITS[opts.format], deck_title, ctx, problems)
        )
        if len(repaired) < MIN_SLIDES:
            raise OutputInvalidError(problems or [f"fewer than {MIN_SLIDES} slides"])
        _check_grounded(repaired, problems)
        kept = shape_deck(repaired, deck_title, SLIDE_COUNTS[opts.length])
        slides = [{"id": f"s{n}", **s} for n, s in enumerate(kept, start=1)]
        subtitle = slide_text(data.get("subtitle"), chars=TITLE_CHARS) or None
        return ProcessedOutput(
            title=deck_title,
            content={"title": deck_title, "subtitle": subtitle, "slides": slides},
            refs_index=build_refs_index((s["refs"] for s in slides), ctx.pack),
        )


HANDLER: ArtifactHandler = SlidesHandler()
