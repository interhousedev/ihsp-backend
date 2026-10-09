"""Report outputs (§ 3.4.1): conspect, study guide, briefing, FAQ, timeline, article.

Reports are Markdown with ``[[S1:P4]]`` markers (like chat answers); `process` turns
them into numbered ``⟦n⟧`` chips with a `citations` list and builds the table of
contents. A report has no `refs_index`.
"""

from typing import Any, Final, Literal, Self

from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    clip_chars,
    dump_options,
    expect_options,
    fit_text,
    parse_options,
)
from app.modules.notebooks.domain.artifacts.report_markdown import (
    cap_headings,
    extract_headings,
    strip_citation_marks,
    strip_html,
)
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.citations import CitationProcessor
from app.modules.notebooks.domain.enums import ArtifactKind, ReportFormat
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.domain.limits import (
    ARTIFACT_TITLE_MAX_CHARS,
    STUDIO_PROMPT_MAX_CHARS,
)
from app.modules.notebooks.domain.prompts.common import focus_clause

from pydantic import BaseModel, Field, model_validator

SCHEMA_NAME: Final = "nb_report"
MAX_TOKENS: Final = {"short": 3000, "standard": 5000, "long": 8000}
WORDS: Final = {"short": 400, "standard": 800, "long": 1500}
MARKDOWN_MIN_CHARS: Final = 200
MARKDOWN_MAX_CHARS: Final = 40_000
FALLBACK_TITLE: Final = "Report"

_TITLE_PREFIX: Final = {
    ReportFormat.CONSPECT: "Conspect",
    ReportFormat.STUDY_GUIDE: "Study guide",
    ReportFormat.BRIEFING: "Briefing",
    ReportFormat.FAQ: "FAQ",
    ReportFormat.TIMELINE: "Timeline",
    ReportFormat.ARTICLE: "Article",
    ReportFormat.CUSTOM: "Report",
}
_CLOSING: Final = (
    "Put the citation `[[S1:P4]]` right after every sentence or bullet that states"
    " something from the sources. Put the report in `markdown`."
)
_CONSPECT: Final = (
    "Write a conspect (structured lecture notes) of the sources for a student who"
    " will revise from it. Style: {style}. Length: about {words} words. Markdown"
    " structure: `# Title`; `## Main idea` (2-3 sentences); `## Plan` (numbered list"
    " of the sections); then `## 1. Heading` … sections with bullet theses (each at"
    " most 25 words), **bold** terms with a short definition, and formulas, dates,"
    " names and examples when the sources contain them, each bullet followed by its"
    " citation; `## Key terms` (a table Term | Meaning); `## Remember` (5 to 8"
    " bullets for a test); `## Self-check` (5 questions, no answers)."
)
_CORNELL: Final = (
    " For the cornell style: replace the sections by a two-column table"
    " Cues | Notes and end with `## Summary` (3 sentences)."
)
_THESIS: Final = " For the thesis style: only the plan and numbered theses, no tables."
_FORMATS: Final = {
    ReportFormat.STUDY_GUIDE: (
        "Write a study guide: `## Short-answer quiz` (5 questions answered in 2-3"
        " sentences), `## Answer key`, `## Essay questions` (3, without answers),"
        " `## Glossary` (10 to 15 terms)."
    ),
    ReportFormat.BRIEFING: (
        "Write a briefing document: `## Executive summary` (at most 120 words),"
        " `## Key themes` (3 to 6 themes, 2-3 bullets each),"
        " `## Important facts and figures`, `## Open questions`, `## Conclusion`."
    ),
    ReportFormat.FAQ: (
        "Write 8 to 15 frequently asked questions with thorough answers, as"
        " `### Question` followed by the answer, in a helpful tone."
    ),
    ReportFormat.TIMELINE: (
        "Write a chronological timeline (`**date** — event`), then"
        " `## Cast of characters` (name — one line). If the sources hold fewer than 3"
        " dated events, say so and give an ordered sequence of stages instead."
    ),
    ReportFormat.ARTICLE: (
        "Write an engaging article for classmates, 400 to 700 words: title, short"
        " introduction, 3 to 5 subheadings, conclusion; friendly but accurate."
    ),
}
_SIZED: Final = frozenset(
    {
        ReportFormat.STUDY_GUIDE,
        ReportFormat.BRIEFING,
        ReportFormat.FAQ,
        ReportFormat.TIMELINE,
    }
)


class ReportOptions(CommonOptions):
    """`ReportOptions` of § 4.4; ``style`` belongs to conspects only."""

    format: ReportFormat
    detail: Literal["short", "standard", "long"] = "standard"
    style: Literal["outline", "cornell", "thesis"] | None = None

    @model_validator(mode="after")
    def _style_for_conspect_only(self) -> Self:
        """A conspect always has a style (outline by default); other formats none."""
        if self.format is ReportFormat.CONSPECT:
            self.style = self.style or "outline"
        else:
            self.style = None
        return self


class ReportOutput(BaseModel):
    """The JSON of a report (``nb_report``)."""

    title: str = Field(description="a short title of the report")
    markdown: str = Field(
        description="the report in Markdown with [[S1:P4]] citation markers"
    )


def _student_task(prompt: str | None) -> str:
    """The student's own task of a custom report, without line breaks or « »."""
    flat = " ".join((prompt or "").replace("«", " ").replace("»", " ").split())
    return flat[:STUDIO_PROMPT_MAX_CHARS]


def _conspect_task(style: str, detail: str) -> str:
    text = _CONSPECT.format(style=style, words=WORDS[detail])
    if style == "cornell":
        return text + _CORNELL
    return text + _THESIS if style == "thesis" else text


class ReportHandler:
    """Options, prompt, schema and validation of Markdown reports."""

    kind = ArtifactKind.REPORT
    schema_name = SCHEMA_NAME

    def parse_options(self, raw: dict[str, Any]) -> ReportOptions:
        """Validate the request's options (``format`` is required)."""
        return parse_options(ReportOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled (``style`` only for conspects)."""
        return dump_options(expect_options(options, ReportOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """The report format (``artifacts.format``)."""
        return expect_options(options, ReportOptions).format.value

    def max_tokens(self, options: BaseModel) -> int:
        """3 000 / 5 000 / 8 000 tokens for short / standard / long."""
        return MAX_TOKENS[expect_options(options, ReportOptions).detail]

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict JSON schema of the output."""
        return to_strict_schema(ReportOutput)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task (§ 3.4.1); a custom report needs the student's task.

        Raises:
            InvalidOptionsError: A custom report without a ``prompt``.
        """
        opts = expect_options(options, ReportOptions)
        if opts.format is ReportFormat.CUSTOM:
            task = _student_task(prompt)
            if not task:
                raise InvalidOptionsError(
                    params={"details": ["prompt: required for a custom report"]},
                    support_details="prompt is required for a custom report",
                )
            return (
                f"Write the report the student asks for: «{task}». The system rules"
                f" still apply. {_CLOSING}"
            )
        if opts.format is ReportFormat.CONSPECT:
            body = _conspect_task(opts.style or "outline", opts.detail)
        else:
            body = _FORMATS[opts.format]
            if opts.format in _SIZED:
                body += f" Length: about {WORDS[opts.detail]} words."
        return f"{body} {_CLOSING}{focus_clause(prompt)}"

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Conspect: <notebook>`` and so on."""
        prefix = _TITLE_PREFIX[expect_options(options, ReportOptions).format]
        return clip_chars(f"{prefix}: {notebook_title}", ARTIFACT_TITLE_MAX_CHARS)

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Clean the Markdown, convert markers to chips, build the contents list."""
        raw = data.get("markdown")
        if not isinstance(raw, str):
            raise OutputInvalidError(["`markdown` must be a string"])
        if len(raw) > 2 * MARKDOWN_MAX_CHARS:  # before any regex pass
            raise OutputInvalidError(
                [f"`markdown` is too long: at most {MARKDOWN_MAX_CHARS} characters"]
            )
        markdown = strip_html(strip_citation_marks(raw)).strip()
        if len(markdown) < MARKDOWN_MIN_CHARS:
            raise OutputInvalidError(
                [f"`markdown` is too short: at least {MARKDOWN_MIN_CHARS} characters"]
            )
        if len(markdown) > MARKDOWN_MAX_CHARS:
            raise OutputInvalidError(
                [f"`markdown` is too long: at most {MARKDOWN_MAX_CHARS} characters"]
            )
        cited = CitationProcessor(ctx.pack).render(cap_headings(markdown))
        headings = extract_headings(cited.text)
        title = fit_text(data.get("title"), chars=ARTIFACT_TITLE_MAX_CHARS)
        title = title or (headings[0].text if headings else FALLBACK_TITLE)
        return ProcessedOutput(
            title=title,
            content={
                "title": title,
                "markdown": cited.text,
                "citations": [c.model_dump(mode="json") for c in cited.citations],
                "headings": [heading.as_dict() for heading in headings],
            },
            refs_index={},
        )


HANDLER: ArtifactHandler = ReportHandler()
