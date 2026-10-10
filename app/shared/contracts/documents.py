"""Document rendering contract (provider: notebooks module, used by the assistant)."""

from dataclasses import dataclass
from typing import Literal, Protocol

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
