"""Groups and their normalized names (ACA-1)."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.schedule.errors import GroupNameInvalidError
from app.shared.text import normalize_group_name, slugify

GroupStatus = Literal["active", "archived"]


@dataclass(slots=True)
class Group:
    """A class group; EMIS names are stored in Latin upper case."""

    id: UUID
    name: str
    slug: str
    emis_group_id: int | None = None
    current_semester: int | None = None
    emis_curriculum_id: int | None = None
    subject_ids: list[UUID] = field(default_factory=list)
    curator_id: UUID | None = None
    head_student_id: UUID | None = None
    status: GroupStatus = "active"


def clean_group_name(raw: str) -> tuple[str, str]:
    """Return (name, slug) for a typed or EMIS group name, or raise if empty."""
    name = normalize_group_name(raw.strip())
    slug = slugify(name)
    if not name or not slug:
        raise GroupNameInvalidError()
    return name, slug
