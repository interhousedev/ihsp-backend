"""Teaching materials the AI produced, stored into the subject notebook.

Lives in shared so `media` can store a finished video without importing `notebooks`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

MaterialKind = Literal[
    "questions", "handout", "lesson_plan", "work_check", "media", "artifact"
]


class TimedText(Protocol):
    """One spoken segment of a media file."""

    @property
    def id(self) -> str:
        """Segment id."""
        ...

    @property
    def speaker(self) -> str:
        """Who speaks."""
        ...

    @property
    def text(self) -> str:
        """What is said."""
        ...

    @property
    def start_ms(self) -> int:
        """Start of the segment in the file."""
        ...

    @property
    def end_ms(self) -> int:
        """End of the segment in the file."""
        ...


@dataclass(frozen=True, slots=True)
class Material:
    """A teaching material with its full text and, for media, its timecodes."""

    kind: MaterialKind
    title: str
    body_md: str
    subject_id: UUID
    group_id: UUID | None
    segments: tuple[TimedText, ...] = ()
    media_file_id: UUID | None = None


class MaterialSink(Protocol):
    """Stores a material in the teacher's subject (or group) notebook."""

    async def store(self, actor: Actor, material: Material) -> object:
        """Store the material as a text source; the same material is stored once."""
        ...
