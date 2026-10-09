"""Tool: read one page of a notebook source's text."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class ReadNotebookSourceArgs(ToolArgs):
    """A source of a notebook and a page number."""

    notebook_id: UUID
    source_id: UUID
    page: int = Field(default=1, ge=1, le=1000)


class ReadNotebookSource(ReadTool[ReadNotebookSourceArgs]):
    """One 8 KB page of a source's text."""

    name = "read_notebook_source"
    description = (
        "Read one page (up to 8 KB of text) of a source of one of the student's "
        "notebooks. Pages start at 1; the result tells how many pages the source "
        "has."
    )
    args_model = ReadNotebookSourceArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(
        self, args: ReadNotebookSourceArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the page; a foreign or unknown source fails the call."""
        return await queries_of(self.bindings).read_source_page(
            ctx.actor.user_id, args.notebook_id, args.source_id, args.page
        )
