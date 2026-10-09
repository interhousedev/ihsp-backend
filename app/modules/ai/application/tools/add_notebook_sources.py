"""Tool (write): add sources to a notebook."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.application.tools.notebook_common import (
    MAX_SOURCES,
    NOTEBOOK_URL,
    SourceArg,
    check_files,
    commands_of,
    notebook_title,
    source_dicts,
    source_names,
)
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.files import FilesApi

from pydantic import Field


class AddNotebookSourcesArgs(ToolArgs):
    """Sources to add to one of the student's notebooks."""

    notebook_id: UUID
    sources: list[SourceArg] = Field(min_length=1, max_length=MAX_SOURCES)


class AddNotebookSources(WriteTool[AddNotebookSourcesArgs]):
    """Adds sources to a notebook after the student approves."""

    name = "add_notebook_sources"
    description = (
        "Add sources to one of the student's notebooks (needs their approval): "
        f"1-{MAX_SOURCES} items, each either "
        '{"kind": "file", "file_id": ...} or {"kind": "text", "title": ..., '
        '"text": ...}. Sources are read in the background.'
    )
    args_model = AddNotebookSourcesArgs

    def __init__(self, files: FilesApi, bindings: LateBindings) -> None:
        """Store the files API and the late-bound notebooks API."""
        self.files = files
        self.bindings = bindings

    async def validate(self, args: AddNotebookSourcesArgs, ctx: ToolContext) -> None:
        """The notebook must be the student's and every file too."""
        commands_of(self.bindings)
        await notebook_title(self.bindings, ctx.actor.user_id, args.notebook_id)
        await check_files(self.files, args.sources, ctx.actor)

    async def preview(
        self, args: AddNotebookSourcesArgs, ctx: ToolContext
    ) -> PreviewData:
        """Show the notebook and the sources that would be added."""
        title = await notebook_title(self.bindings, ctx.actor.user_id, args.notebook_id)
        return PreviewData(
            title_key="ai-preview-add-notebook-sources",
            title_params={"title": title, "count": len(args.sources)},
            fields=[PreviewField(label_key="ai-field-notebook", value=title)],
            items=await source_names(self.files, args.sources),
        )

    async def run(
        self, args: AddNotebookSourcesArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Add the sources; return the created ones and how many were refused."""
        created = await commands_of(self.bindings).add_sources(
            ctx.actor, args.notebook_id, source_dicts(args.sources)
        )
        return {
            "notebook_id": str(args.notebook_id),
            "added": created,
            "rejected": len(args.sources) - len(created),
            "url": NOTEBOOK_URL.format(notebook_id=args.notebook_id),
        }
