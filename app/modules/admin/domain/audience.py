"""Who receives a broadcast (stored as jsonb, validated on read and write)."""

from uuid import UUID

from app.shared.actor import Role

from pydantic import BaseModel, Field


class Audience(BaseModel):
    """Everyone, or the union of roles, groups and semesters."""

    everyone: bool = False
    roles: list[Role] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)
    semesters: list[int] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True if nothing selects any recipient."""
        return not (self.everyone or self.roles or self.group_ids or self.semesters)
