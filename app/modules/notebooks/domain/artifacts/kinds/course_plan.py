"""Course plan (course workspaces): learning outcomes, sections and steps.

The model writes the plan as JSON; `process` validates it against `CoursePlanInput`
of the LMS block contracts, section by section and step by step (a broken step is
dropped and reported, a plan without a valid section is sent back for repair). The
stored document is the plan plus `refs` on every section and step, so the viewer can
show where an idea comes from; the Apply action writes only the plan (titles, goals,
summaries) into the course draft.
"""

from typing import Any, Final, Literal

from app.modules.notebooks.domain.artifacts.course_text import (
    clean_item_title,
    strip_ref_labels,
)
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
    norm_key,
    parse_options,
    require_list,
    validate_numbered,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index, valid_refs
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.course import TOPIC_MAX_CHARS, plan_task
from app.shared.contracts.lms_blocks import CoursePlanInput

from pydantic import BaseModel, Field, ValidationError, field_validator

SCHEMA_NAME: Final = "nb_course_plan"
MAX_TOKENS: Final = {"overview": 4_000, "detailed": 8_000}
TITLE_CHARS: Final = 200
GOAL_CHARS: Final = 300
SUMMARY_CHARS: Final = 1_200
COURSE_SUMMARY_CHARS: Final = 2_000
MAX_GOALS: Final = 6
MAX_COURSE_GOALS: Final = 10
MAX_SECTIONS: Final = 30
MAX_STEPS: Final = 30
FALLBACK_TITLE: Final = "Course plan"


class CoursePlanOptions(CommonOptions):
    """Options of a course plan: how deep, what to concentrate on, how many sections."""

    depth: Literal["overview", "detailed"] = "overview"
    focus: str | None = Field(default=None, max_length=TOPIC_MAX_CHARS)
    sections_hint: int | None = Field(default=None, ge=1, le=MAX_SECTIONS)

    @field_validator("focus")
    @classmethod
    def _blank_focus_is_none(cls, value: str | None) -> str | None:
        """An empty or blank focus means no focus."""
        return (value or "").strip() or None


class PlanStepOut(BaseModel):
    """A planned step as the model writes it."""

    title: str = Field(description="what the step teaches, a short noun phrase")
    goals: list[str] | None = Field(
        default=None, description="measurable outcomes, one verb phrase each"
    )
    summary: str | None = Field(
        default=None, description="content, practice and check of the step"
    )
    refs: list[str] | None = Field(
        default=None, description="passage labels such as S1:P4 that support the step"
    )


class PlanSectionOut(BaseModel):
    """A planned section as the model writes it."""

    title: str = Field(description="the theme of the section")
    goals: list[str] | None = Field(
        default=None, description="measurable outcomes of the section"
    )
    refs: list[str] | None = Field(
        default=None, description="passage labels that support the section"
    )
    steps: list[PlanStepOut]


class CoursePlanOut(BaseModel):
    """The JSON document of the model (`nb_course_plan`)."""

    title: str = Field(description="a short working name of the course")
    summary: str | None = Field(default=None, description="overview of the course")
    goals: list[str] | None = Field(
        default=None, description="learning outcomes of the whole course"
    )
    sections: list[PlanSectionOut]


class _SectionHead(BaseModel):
    """A section without its steps (they are validated one by one)."""

    title: str
    goals: list[str] | None = None
    refs: list[str] | None = None
    steps: list[Any]


def _goals(raw: list[str] | None, limit: int) -> list[str]:
    """Distinct, non-empty goals, at most `limit` of them."""
    seen: dict[str, str] = {}
    for item in raw or []:
        goal = fit_text(strip_ref_labels(item), chars=GOAL_CHARS)
        if goal:
            seen.setdefault(norm_key(goal), goal)
    return list(seen.values())[:limit]


def _step(item: PlanStepOut, pack: ContextPack) -> dict[str, Any] | None:
    """A cleaned step, or None when its title is empty."""
    title = clean_item_title(item.title, TITLE_CHARS)
    if not title:
        return None
    return {
        "title": title,
        "goals": _goals(item.goals, MAX_GOALS),
        "summary": fit_text(strip_ref_labels(item.summary or ""), chars=SUMMARY_CHARS),
        "refs": valid_refs(item.refs or [], pack),
    }


def _steps(
    raw: list[Any], number: int, pack: ContextPack, problems: list[str]
) -> list[dict[str, Any]]:
    """The valid, distinct steps of section `number` (at most 30)."""
    items = validate_numbered(PlanStepOut, raw, problems, f"section {number} step")
    steps: dict[str, dict[str, Any]] = {}
    for _, item in items:
        step = _step(item, pack)
        if step is not None:
            steps.setdefault(norm_key(step["title"]), step)
    return list(steps.values())[:MAX_STEPS]


def _section(
    raw: Any, number: int, pack: ContextPack, problems: list[str]
) -> dict[str, Any] | None:
    """A cleaned section with its steps, or None (the reason is in `problems`)."""
    heads = validate_numbered(_SectionHead, [raw], [], "section")
    if not heads:
        problems.append(f"section {number}: needs a `title` and a list of `steps`")
        return None
    head = heads[0][1]
    title = clean_item_title(head.title, TITLE_CHARS)
    steps = _steps(head.steps, number, pack, problems)
    if not title or not steps:
        problems.append(f"section {number}: needs a title and at least one step")
        return None
    return {
        "title": title,
        "goals": _goals(head.goals, MAX_GOALS),
        "refs": valid_refs(head.refs or [], pack),
        "steps": steps,
    }


def _sections(
    data: dict[str, Any], pack: ContextPack, problems: list[str]
) -> list[dict[str, Any]]:
    """The valid, distinct sections (at most 30), in the model's order."""
    found: dict[str, dict[str, Any]] = {}
    for number, raw in enumerate(require_list(data, "sections"), start=1):
        section = _section(raw, number, pack, problems)
        if section is not None:
            found.setdefault(norm_key(section["title"]), section)
    return list(found.values())[:MAX_SECTIONS]


def _all_refs(sections: list[dict[str, Any]]) -> list[list[str]]:
    """The ref lists of every section and step, in reading order."""
    refs: list[list[str]] = []
    for section in sections:
        refs.append(section["refs"])
        refs.extend(step["refs"] for step in section["steps"])
    return refs


class CoursePlanHandler:
    """Options, prompt, schema and validation of the course plan."""

    kind: ArtifactKind = ArtifactKind.COURSE_PLAN
    schema_name: str = SCHEMA_NAME

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(CoursePlanOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled."""
        return dump_options(expect_options(options, CoursePlanOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """A plan has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """4 000 for an overview, 8 000 for a detailed plan."""
        return MAX_TOKENS[expect_options(options, CoursePlanOptions).depth]

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `CoursePlanOut`."""
        return to_strict_schema(CoursePlanOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (the course part is added by the engine)."""
        opts = expect_options(options, CoursePlanOptions)
        return plan_task(opts.depth, opts.sections_hint, opts.focus, prompt)

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """``Course plan: <notebook>``."""
        return f"{FALLBACK_TITLE}: {notebook_title}"[:ARTIFACT_TITLE_MAX_CHARS]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Validate the plan, clean titles and goals, resolve refs.

        Raises:
            OutputInvalidError: No section with a step is left.
        """
        expect_options(options, CoursePlanOptions)
        problems: list[str] = []
        sections = _sections(data, ctx.pack, problems)
        if not sections:
            raise OutputInvalidError(problems or ["no valid sections"])
        fallback = ctx.pack.course.title if ctx.pack.course else FALLBACK_TITLE
        title = document_title(data, ctx.pack, fallback)
        content: dict[str, Any] = {
            "title": title,
            "language": ctx.language,
            "summary": fit_text(
                strip_ref_labels(str(data.get("summary") or "")),
                chars=COURSE_SUMMARY_CHARS,
            ),
            "goals": _goals(_string_list(data.get("goals")), MAX_COURSE_GOALS),
            "sections": sections,
        }
        try:
            CoursePlanInput.model_validate(content)
        except ValidationError as exc:
            error = exc.errors(include_url=False, include_input=False)[0]
            where = ".".join(str(part) for part in error["loc"])
            raise OutputInvalidError([f"plan: {where}: {error['msg']}"]) from exc
        return ProcessedOutput(
            title=title,
            content=content,
            refs_index=build_refs_index(_all_refs(sections), ctx.pack),
        )


def _string_list(value: object) -> list[str]:
    """The strings of a JSON list; anything else gives an empty list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


HANDLER: ArtifactHandler = CoursePlanHandler()
