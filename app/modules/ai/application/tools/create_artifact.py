"""Tool (write): request a Studio output (report, quiz, mind map, ...)."""

from typing import Any, Literal
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.application.tools.notebook_common import (
    NOTEBOOK_URL,
    commands_of,
    queries_of,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField

from pydantic import Field

ArtifactKindName = Literal[
    "report",
    "mind_map",
    "flashcards",
    "quiz",
    "exercise",
    "data_table",
    "slides",
    "infographic",
]
REPORT_FORMATS = (
    "conspect",
    "study_guide",
    "briefing",
    "faq",
    "timeline",
    "article",
    "custom",
)
OPTIONS_MAX_CHARS = 500
PROMPT_MAX_CHARS = 1000
UNUSABLE = ("failed", "unavailable")


class CreateArtifactArgs(ToolArgs):
    """A Studio output to generate from a notebook's selected sources."""

    notebook_id: UUID
    kind: ArtifactKindName
    options: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = Field(default=None, max_length=PROMPT_MAX_CHARS)


def options_text(options: dict[str, Any]) -> str:
    """Return the options as ``key: value`` pairs for the approval card."""
    parts = []
    for key in sorted(options):
        value = options[key]
        shown = "/".join(map(str, value)) if isinstance(value, list) else value
        parts.append(f"{key}: {shown}")
    return ", ".join(parts)[:OPTIONS_MAX_CHARS]


class CreateArtifact(WriteTool[CreateArtifactArgs]):
    """Queues an output after the student approves it; it counts as one of 20 a day."""

    name = "create_artifact"
    description = (
        "Generate a study material from the selected sources of one of the student's "
        "notebooks (needs their approval; it uses one of their daily outputs). kind: "
        "report, mind_map, flashcards, quiz, exercise, data_table, slides or "
        "infographic. options: for a report {format: conspect | study_guide | "
        "briefing | faq | timeline | article | custom, detail?: short | standard | "
        "long}; flashcards {count?: fewer | standard | more, difficulty?: easy | "
        "medium | hard}; quiz the same plus {types?: [single, multiple, true_false]};"
        " exercise (an exam-style practice set: passages with typed questions, or a "
        "writing task with a band rubric) {exam?: ielts_academic | sat | ap | "
        "generic, skill?: reading | writing | listening_script | mixed, count?: 1-60,"
        " difficulty?: easy | medium | hard}; mind_map {detail?: overview | "
        "detailed}; data_table {max_rows?: 10-40}; slides {format?: presenter | "
        "detailed, length?: short | default | long}; infographic {orientation?: "
        "portrait | landscape | square, detail?: concise | standard | detailed, "
        "style?: clean | sketch | bento | scientific | playful}; any kind may have "
        "{language?: uz | ru | en}. prompt focuses the output (required for a custom "
        "report). The output is generated in the background."
    )
    args_model = CreateArtifactArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def _notebook(
        self, args: CreateArtifactArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        found = await queries_of(self.bindings).get_notebook(
            ctx.actor.user_id, args.notebook_id
        )
        if found is None:
            raise ToolFailedError(support_details="notebook not found")
        return found

    @staticmethod
    def _check_options(args: CreateArtifactArgs) -> None:
        if args.kind != "report":
            return
        fmt = args.options.get("format")
        if fmt not in REPORT_FORMATS:
            raise ToolFailedError(
                support_details=(
                    "options.format is required for a report: "
                    + ", ".join(REPORT_FORMATS)
                )
            )
        if fmt == "custom" and not (args.prompt or "").strip():
            raise ToolFailedError(
                support_details="a custom report needs a prompt that says what to write"
            )

    async def _check_quota(
        self, args: CreateArtifactArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        usage = await queries_of(self.bindings).usage(ctx.actor.user_id)
        for name in ("artifacts", args.kind):
            part = usage.get(name)
            if part is not None and part["used"] >= part["limit"]:
                raise ToolFailedError(
                    support_details=(
                        f"the daily limit of outputs is reached ({part['used']} of "
                        f"{part['limit']}); it resets at {part.get('resets_at')}"
                    )
                )
        return dict(usage.get("artifacts") or {})

    async def validate(self, args: CreateArtifactArgs, ctx: ToolContext) -> None:
        """Notebook, options and the daily quota must allow the output."""
        commands_of(self.bindings)
        await self._notebook(args, ctx)
        self._check_options(args)
        await self._check_quota(args, ctx)

    async def preview(self, args: CreateArtifactArgs, ctx: ToolContext) -> PreviewData:
        """Show the output, the notebook, its options, sources and the quota."""
        notebook = await self._notebook(args, ctx)
        quota = await self._check_quota(args, ctx)
        title = str(notebook.get("title", ""))
        fields = [PreviewField(label_key="ai-field-notebook", value=title)]
        if args.options:
            fields.append(
                PreviewField(
                    label_key="ai-field-options", value=options_text(args.options)
                )
            )
        if args.prompt:
            fields.append(PreviewField(label_key="ai-field-prompt", value=args.prompt))
        return PreviewData(
            title_key="ai-preview-create-artifact-" + args.kind.replace("_", "-"),
            title_params={
                "title": title,
                "used": quota.get("used", 0),
                "limit": quota.get("limit", 0),
            },
            fields=fields,
            items=_source_titles(notebook, args.options),
        )

    async def run(self, args: CreateArtifactArgs, ctx: ToolContext) -> dict[str, Any]:
        """Queue the output; return its id, status and a link to the notebook."""
        created = await commands_of(self.bindings).request_artifact(
            ctx.actor, args.notebook_id, args.kind, args.options, args.prompt
        )
        return {
            **created,
            "notebook_id": str(args.notebook_id),
            "url": NOTEBOOK_URL.format(notebook_id=args.notebook_id)
            + f"&artifact={created.get('id')}",
        }


def _source_titles(notebook: dict[str, Any], options: dict[str, Any]) -> list[str]:
    """Titles of the sources the output would use: chosen ones or the selected."""
    chosen = options.get("source_ids")
    rows = [s for s in notebook.get("sources", []) if s["status"] not in UNUSABLE]
    if isinstance(chosen, list) and chosen:
        wanted = {str(c) for c in chosen}
        return [str(s["title"]) for s in rows if s["id"] in wanted]
    return [str(s["title"]) for s in rows if s.get("selected", True)]
