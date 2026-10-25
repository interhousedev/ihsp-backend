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


class MaterialScope(StrEnum):
    """Who a subject material is for."""

    ADMIN = "admin"  # every subject notebook of the EMIS subject id
    TEACHER_SUBJECT = "teacher_subject"  # the groups a teacher has for the subject
    GROUP = "group"  # one group (or subgroup) of a teacher for the subject


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
    scope: MaterialScope = MaterialScope.ADMIN
    teacher_id: UUID | None = None  # the teacher of a teacher-subject or group material
    group_id: UUID | None = None  # group materials only
    subgroup: int | None = None  # group materials: None is the whole group

    def same_target(self, other: "DefaultMaterial") -> bool:
        """True when both are the same file, link or library item."""
        return (self.kind, self.file_id, self.url, self.library_item_id) == (
            other.kind,
            other.file_id,
            other.url,
            other.library_item_id,
        )

    def applies_to(self, audience: "MaterialAudience") -> bool:
        """True when a subject notebook with this audience gets the material."""
        if self.scope is MaterialScope.ADMIN:
            return True
        if self.teacher_id is None or self.teacher_id not in audience.teacher_ids:
            return False
        if self.scope is MaterialScope.TEACHER_SUBJECT:
            return True
        return any(
            group_id == self.group_id and self._subgroup_matches(sub, audience)
            for group_id, sub in audience.groups
        )

    def _subgroup_matches(self, sub: int | None, audience: "MaterialAudience") -> bool:
        if self.subgroup is None or sub == self.subgroup:
            return True  # a whole-group material, or the same subgroup
        # A teacher of the whole group sees its subgroups' materials; a student
        # without a subgroup yet sees the whole-group ones only.
        return sub is None and not audience.is_student


@dataclass(frozen=True, slots=True)
class MaterialAudience:
    """Whose subject notebook it is: the teachers it follows and the groups it is in.

    A student has the teachers of their lessons of the subject and their one group
    (with the subgroup). A teacher has themselves and every (group, subgroup) they
    teach the subject to.
    """

    teacher_ids: frozenset[UUID]
    groups: tuple[tuple[UUID, int | None], ...]
    is_student: bool = True


def default_material_of(source: Source) -> str | None:
    """The id (text) of the default material a source is a copy of, if it is one."""
    value = (source.origin or {}).get(DEFAULT_MARK)
    return None if value is None else str(value)


def is_default_copy(source: Source) -> bool:
    """True for a source a default material put into a subject notebook."""
    return default_material_of(source) is not None
