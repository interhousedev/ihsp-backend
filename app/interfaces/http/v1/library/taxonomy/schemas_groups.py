"""Response model of `GET /v1/library/my-groups`."""

from typing import Self
from uuid import UUID

from app.modules.library.ports.directories import GroupView

from pydantic import BaseModel


class GroupResponse(BaseModel):
    """A study group a reading list can be aimed at."""

    id: UUID
    name: str

    @classmethod
    def from_view(cls, view: GroupView) -> Self:
        """Map the read model."""
        return cls(id=view.id, name=view.name)
