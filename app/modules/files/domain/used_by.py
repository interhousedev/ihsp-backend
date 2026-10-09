"""Where a file is used (for 'used by' lists and safe deletion)."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UsedBy:
    """One place that refers to a file."""

    kind: Literal["link", "lesson", "chat", "notebook"]
    id: UUID
    label: str
