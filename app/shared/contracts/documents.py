"""Document rendering contract (provider: notebooks module, used by the assistant)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

DocumentKind = Literal["docx", "xlsx", "pptx"]


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    """An Office file ready to be stored."""

    name: str
    content_type: str
    data: bytes


class DocumentRenderer(Protocol):
    """Turns plain text written by the assistant into an Office file."""

    def render(self, kind: DocumentKind, title: str, content: str) -> RenderedDocument:
        """Render ``content`` (Markdown, a table or a slide outline) as ``kind``."""
        ...

    def render_slides(
        self, title: str, slides: Sequence[dict[str, Any]]
    ) -> RenderedDocument:
        """Render slides (``title``, ``bullets``, ``notes``) as a .pptx."""
        ...

    def render_blocks(
        self, title: str, blocks: Sequence[dict[str, Any]]
    ) -> RenderedDocument:
        """Render blocks (heading, paragraph, bullets, table) as a .docx."""
        ...

    def render_sheets(
        self, title: str, sheets: Sequence[dict[str, Any]]
    ) -> RenderedDocument:
        """Render sheets (``name``, ``columns``, ``rows``) as an .xlsx."""
        ...
