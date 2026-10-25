"""Tools: build a presentation, a document or a spreadsheet from structured parts.

The file is stored in the user's own files (the per-user quota applies: a full
quota comes back to the model as a failed tool result) and shown as a file card.
"""

from abc import abstractmethod
from typing import Any, Literal

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import A, ReadTool, Tool, ToolContext
from app.modules.ai.application.tools.make_document import scope_of
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.documents import (
    DocumentKind,
    DocumentRenderer,
    RenderedDocument,
)
from app.shared.contracts.files import FilePurpose, FilesApi

from pydantic import Field

MAX_SLIDES = 30
MAX_BULLETS = 12
MAX_BLOCKS = 200
MAX_SHEETS = 10
MAX_COLUMNS = 50
MAX_ROWS = 2000
TEXT_MAX = 4000
CELL_MAX = 2000

Cell = str | int | float


class SlideArgs(ToolArgs):
    """One slide: a title, bullet points and optional speaker notes."""

    title: str = Field(max_length=200)
    bullets: list[str] = Field(max_length=MAX_BULLETS)
    notes: str | None = Field(default=None, max_length=TEXT_MAX)


class CreatePresentationArgs(ToolArgs):
    """The deck title and its slides."""

    title: str = Field(min_length=1, max_length=120)
    slides: list[SlideArgs] = Field(min_length=1, max_length=MAX_SLIDES)


class BlockArgs(ToolArgs):
    """One block of a document; the fields used depend on ``type``."""

    type: Literal["heading", "paragraph", "bullets", "table"]
    text: str | None = Field(default=None, max_length=TEXT_MAX)
    level: int | None = Field(default=None, ge=1, le=3)
    items: list[str] | None = Field(default=None, max_length=100)
    columns: list[str] | None = Field(default=None, max_length=MAX_COLUMNS)
    rows: list[list[Cell]] | None = Field(default=None, max_length=500)


class CreateDocumentArgs(ToolArgs):
    """The document title and its blocks in reading order."""

    title: str = Field(min_length=1, max_length=120)
    blocks: list[BlockArgs] = Field(min_length=1, max_length=MAX_BLOCKS)


class SheetArgs(ToolArgs):
    """One sheet: its name, the header row and the data rows."""

    name: str = Field(min_length=1, max_length=31)
    columns: list[str] = Field(min_length=1, max_length=MAX_COLUMNS)
    rows: list[list[Cell]] = Field(max_length=MAX_ROWS)


class CreateSpreadsheetArgs(ToolArgs):
    """The workbook title and its sheets."""

    title: str = Field(min_length=1, max_length=120)
    sheets: list[SheetArgs] = Field(min_length=1, max_length=MAX_SHEETS)


class _CreateOfficeFile(ReadTool[A]):
    """Renders the parts, stores the file for the user, returns the file card."""

    kind: DocumentKind

    def __init__(self, files: FilesApi, bindings: LateBindings) -> None:
        """Store the files API and the late-bound renderer."""
        self.files = files
        self.bindings = bindings

    @abstractmethod
    def render(self, renderer: DocumentRenderer, args: A) -> RenderedDocument:
        """Build the file from the arguments."""

    async def run(self, args: A, ctx: ToolContext) -> dict[str, Any]:
        """Render, store under the user's quota and return the card fields."""
        renderer = self.bindings.documents
        if renderer is None:
            raise ToolFailedError(support_details="documents are unavailable")
        document = self.render(renderer, args)
        ref = await self.files.store_bytes(
            owner_id=ctx.actor.user_id,
            scope=scope_of(ctx.actor),
            purpose=FilePurpose.AI_UPLOAD,
            name=document.name,
            data=document.data,
        )
        return {
            "file_id": str(ref.id),
            "name": ref.name,
            "kind": self.kind,
            "size": ref.byte_size,
        }


def _dump(parts: list[Any]) -> list[dict[str, Any]]:
    """Plain dicts for the renderer."""
    return [p.model_dump() for p in parts]


class CreatePresentation(_CreateOfficeFile[CreatePresentationArgs]):
    """A .pptx deck."""

    name = "create_presentation"
    kind: DocumentKind = "pptx"
    description = (
        "Create a PowerPoint presentation (.pptx) in the user's My files and show "
        f"it in the chat. Up to {MAX_SLIDES} slides, each with a title, short "
        "bullets and optional speaker notes. Use only when the user asks for a "
        "presentation or slides. Do not repeat the slides in your answer."
    )
    args_model = CreatePresentationArgs

    def render(
        self, renderer: DocumentRenderer, args: CreatePresentationArgs
    ) -> RenderedDocument:
        """Render the slides."""
        return renderer.render_slides(args.title, _dump(args.slides))


class CreateDocument(_CreateOfficeFile[CreateDocumentArgs]):
    """A .docx document."""

    name = "create_document"
    kind: DocumentKind = "docx"
    description = (
        "Create a Word document (.docx) in the user's My files and show it in the "
        "chat. blocks in order: heading (text, level 1-3), paragraph (text), "
        "bullets (items), table (columns, rows). Use only when the user asks for a "
        "document or file. Do not repeat the text in your answer."
    )
    args_model = CreateDocumentArgs

    def render(
        self, renderer: DocumentRenderer, args: CreateDocumentArgs
    ) -> RenderedDocument:
        """Render the blocks."""
        return renderer.render_blocks(args.title, _dump(args.blocks))


class CreateSpreadsheet(_CreateOfficeFile[CreateSpreadsheetArgs]):
    """An .xlsx workbook."""

    name = "create_spreadsheet"
    kind: DocumentKind = "xlsx"
    description = (
        "Create an Excel spreadsheet (.xlsx) in the user's My files and show it in "
        f"the chat. Sheets with a name, header columns and up to {MAX_ROWS} rows; "
        "cells are strings or numbers. Use only when the user asks for a table or "
        "spreadsheet file. Do not repeat the table in your answer."
    )
    args_model = CreateSpreadsheetArgs

    def render(
        self, renderer: DocumentRenderer, args: CreateSpreadsheetArgs
    ) -> RenderedDocument:
        """Render the sheets."""
        return renderer.render_sheets(args.title, _dump(args.sheets))


def make_office_tools(files: FilesApi, bindings: LateBindings) -> list[Tool]:
    """The three file-making tools, in their fixed order."""
    return [
        CreatePresentation(files, bindings),
        CreateDocument(files, bindings),
        CreateSpreadsheet(files, bindings),
    ]
