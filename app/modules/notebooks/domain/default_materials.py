"""Default materials of subjects: what every student's subject notebook starts with.

An admin adds a file, a link or a library book to an EMIS subject id (the subject need
not exist in our database yet). Each student's subject notebook of that subject then
gets a copy of it. A copy is a derived source like a lesson material: the sync keeps it
while the default material exists and the student does not exclude it, so it is
marked with the origin key `DEFAULT_MARK` (the id of the default material).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.entities import Source

MAX_DEFAULT_MATERIALS: Final = 30  # per EMIS subject id
DEFAULT_MATERIAL_TITLE_MAX_CHARS: Final = 255
DEFAULT_MARK: Final = "subject_default"  # origin key: the default material a copy is of


class DefaultMaterialKind(StrEnum):
    """Where a default material's text comes from."""

    FILE = "file"  # a file the admin uploaded (My files of the admin)
    LINK = "link"  # a web page, read like a URL source
    LIBRARY_ITEM = "library_item"  # a library book or material, whole


@dataclass(frozen=True, slots=True)
class DefaultMaterial:
    """One default material of an EMIS subject id."""

    id: UUID
    edu_subject_id: int
    kind: DefaultMaterialKind
    title: str
    position: int
    created_by: UUID
    created_at: datetime
    file_id: UUID | None = None
    url: str | None = None
    library_item_id: UUID | None = None

    def same_target(self, other: "DefaultMaterial") -> bool:
        """True when both are the same file, link or library item."""
        return (self.kind, self.file_id, self.url, self.library_item_id) == (
            other.kind,
            other.file_id,
            other.url,
            other.library_item_id,
        )


def default_material_of(source: Source) -> str | None:
    """The id (text) of the default material a source is a copy of, if it is one."""
    value = (source.origin or {}).get(DEFAULT_MARK)
    return None if value is None else str(value)


def is_default_copy(source: Source) -> bool:
    """True for a source a default material put into a subject notebook."""
    return default_material_of(source) is not None
