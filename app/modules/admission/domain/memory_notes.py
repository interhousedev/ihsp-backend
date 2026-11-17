"""Memory notes: short facts a student's AI agent keeps about the student.

Notes are written from the app, by an MCP client holding `admission:memory`, or by
the admission assistant. Only the student sees, writes and deletes them; the
assistant reads them as context.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import CharLimitError, ItemLimitError

CONTENT_MAX: Final = 4000
NOTES_MAX: Final = 200  # per student; the oldest is not dropped silently
NoteSource = Literal["app", "mcp", "assistant"]
SOURCES: Final[tuple[NoteSource, ...]] = ("app", "mcp", "assistant")


@dataclass(frozen=True, slots=True)
class MemoryNote:
    """One note of one student."""

    id: UUID
    student_id: UUID
    content: str
    source: NoteSource
    created_at: datetime


def clean_content(content: str) -> str:
    """Strip the note; raise CharLimitError when empty or over CONTENT_MAX."""
    text = content.strip()
    if not text or len(text) > CONTENT_MAX:
        raise CharLimitError(params={"field": "content", "limit": CONTENT_MAX})
    return text


def check_room(count: int) -> None:
    """Raise ItemLimitError when the student already has NOTES_MAX notes."""
    if count >= NOTES_MAX:
        raise ItemLimitError(params={"kind": "memory_note", "limit": NOTES_MAX})
