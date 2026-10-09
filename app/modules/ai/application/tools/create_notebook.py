"""Tool (write): create a notebook with sources."""

from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.application.tools.notebook_common import (
    MAX_SOURCES,
    NOTEBOOK_URL,
    SourceArg,
    check_files,
    commands_of,
    source_dicts,
    source_names,
)
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.files import FilesApi

from pydantic import Field

TITLE_MAX = 120


class CreateNotebookArgs(ToolArgs):
    """A new notebook with its sources."""

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    sources: list[SourceArg] = Field(min_length=1, max_length=MAX_SOURCES)


class CreateNotebook(WriteTool[CreateNotebookArgs]):
    """Creates a notebook after the student approves it."""

    name = "create_notebook"
    description = (
        "Create a notebook for the student (needs their approval) and add sources "
        f"to it: 1-{MAX_SOURCES} items, each either "
        '{"kind": "file", "file_id": ...} for one of the student\'s files or '
        '{"kind": "text", "title": ..., "text": ...} for text. Files are read in '
        "the background; use it for files that are too large for read_file."
    )
    args_model = CreateNotebookArgs

    def __init__(self, files: FilesApi, bindings: LateBindings) -> None:
        """Store the files API and the late-bound notebooks API."""
        self.files = files
        self.bindings = bindings

    async def validate(self, args: CreateNotebookArgs, ctx: ToolContext) -> None:
        """The notebooks API must exist and every file must be the student's."""
        commands_of(self.bindings)
        await check_files(self.files, args.sources, ctx.actor)

    async def preview(self, args: CreateNotebookArgs, ctx: ToolContext) -> PreviewData:
        """Show the title and the sources that would be added."""
        return PreviewData(
            title_key="ai-preview-create-notebook",
            title_params={"title": args.title, "count": len(args.sources)},
            fields=[PreviewField(label_key="ai-field-title", value=args.title)],
            items=await source_names(self.files, args.sources),
        )

    async def run(self, args: CreateNotebookArgs, ctx: ToolContext) -> dict[str, Any]:
        """Create the notebook; return its id, link and what was added or refused."""
        created = await commands_of(self.bindings).create_notebook(
            ctx.actor, args.title, source_dicts(args.sources)
        )
        return {**created, "url": NOTEBOOK_URL.format(notebook_id=created.get("id"))}
