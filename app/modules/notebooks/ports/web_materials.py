"""Port: files and media linked from a web page, gathered for its notebook."""

from dataclasses import dataclass
from typing import Literal, Protocol

MaterialKind = Literal["document", "image", "audio"]


@dataclass(frozen=True, slots=True)
class MaterialCandidate:
    """A file the page links to or shows in its article, not yet downloaded."""

    url: str  # absolute http(s)
    kind: MaterialKind
    title: str  # link text, alt text or the file name
    context: str  # text around it on the page (for the triage model)


@dataclass(frozen=True, slots=True)
class DownloadedMaterial:
    """The checked bytes of one candidate."""

    url: str  # after redirects
    content_type: str
    data: bytes


class MaterialFetcher(Protocol):
    """Reads the candidates of a page and downloads them, safe against SSRF."""

    async def candidates(self, page_url: str, limit: int) -> list[MaterialCandidate]:
        """The linked files of the page (empty when it is not HTML or unreachable)."""
        ...

    async def download(self, url: str, max_bytes: int) -> DownloadedMaterial:
        """Download one file; raise `SourceReadError` on any problem.

        Codes: forbidden, fetch_failed, unsupported_type, too_large.
        """
        ...
