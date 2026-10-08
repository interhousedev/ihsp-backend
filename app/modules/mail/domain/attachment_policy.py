"""Which attachments of an incoming mail are stored and forwarded (MAIL-2, FILE-4)."""

import posixpath
from dataclasses import dataclass

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS = 20
SNIFF_BYTES = 8192

_OOXML = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    **{ext: frozenset({mime}) for ext, mime in _OOXML.items()},
}
# Mail clients often label real documents with a generic type.
_GENERIC = frozenset({"application/octet-stream", "binary/octet-stream", ""})
_SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".docx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
}


@dataclass(frozen=True, slots=True)
class AttachmentVerdict:
    """Store the attachment, or skip it and list its name."""

    allowed: bool
    reason: str | None = None


def _extension(name: str) -> str:
    return posixpath.splitext(name.lower())[1]


def _content_matches(extension: str, head: bytes) -> bool:
    signatures = _SIGNATURES.get(extension)
    if signatures is None:  # .txt and .md: text has no NUL bytes
        return b"\x00" not in head
    return head.startswith(signatures)


def judge_attachment(name: str, content_type: str, data: bytes) -> AttachmentVerdict:
    """Allow FILE-4 types up to 50 MB whose bytes agree with name and type."""
    extension = _extension(name)
    allowed_types = _TYPES.get(extension)
    if allowed_types is None:
        return AttachmentVerdict(False, "type")
    if content_type.lower() not in allowed_types | _GENERIC:
        return AttachmentVerdict(False, "type")
    if len(data) > MAX_ATTACHMENT_BYTES:
        return AttachmentVerdict(False, "size")
    if not data or not _content_matches(extension, data[:SNIFF_BYTES]):
        return AttachmentVerdict(False, "content")
    return AttachmentVerdict(True)
