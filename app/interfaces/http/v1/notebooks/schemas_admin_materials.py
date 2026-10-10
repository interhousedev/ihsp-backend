"""Schemas of the admin routes of the default materials of subjects."""

from datetime import datetime
from typing import Self
from uuid import UUID

from app.modules.notebooks.domain.default_materials import (
    DefaultMaterial,
    DefaultMaterialKind,
)

from pydantic import BaseModel, Field, model_validator


class SubjectMaterialCreateBody(BaseModel):
    """Body of POST /v1/admin/subject-materials/{edu_subject_id}.

    Exactly the target that `kind` names is given: a file id, a link or a library
    item id.
    """

    kind: DefaultMaterialKind
    title: str = Field(min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2048)
    file_id: UUID | None = None
    library_item_id: UUID | None = None

    @model_validator(mode="after")
    def _exactly_the_target_of_the_kind(self) -> Self:
        """No target of another kind, and the target of this kind is there."""
        given = {
            kind
            for kind, value in (
                (DefaultMaterialKind.FILE, self.file_id),
                (DefaultMaterialKind.LINK, self.url or None),
                (DefaultMaterialKind.LIBRARY_ITEM, self.library_item_id),
            )
            if value is not None
        }
        if given != {self.kind}:
            raise ValueError("give exactly the file, link or library item of the kind")
        return self


class SubjectMaterialResponse(BaseModel):
    """One default material of an EMIS subject id."""

    id: UUID
    edu_subject_id: int
    kind: DefaultMaterialKind
    title: str
    url: str | None
    file_id: UUID | None
    library_item_id: UUID | None
    position: int
    created_at: datetime

    @classmethod
    def from_entity(cls, material: DefaultMaterial) -> Self:
        """The response of a stored default material."""
        return cls(
            id=material.id,
            edu_subject_id=material.edu_subject_id,
            kind=material.kind,
            title=material.title,
            url=material.url,
            file_id=material.file_id,
            library_item_id=material.library_item_id,
            position=material.position,
            created_at=material.created_at,
        )


class SubjectMaterialGroupResponse(BaseModel):
    """The default materials of one EMIS subject id."""

    edu_subject_id: int
    materials: list[SubjectMaterialResponse]
