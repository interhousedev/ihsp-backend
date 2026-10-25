"""Inputs of the material use cases (the HTTP layer maps its bodies onto these)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.domain.enums import ItemLanguage, ItemType, MaterialLicence


@dataclass(frozen=True, slots=True)
class MaterialData:
    """What an uploader fills in the form (`MaterialInput` of the contract)."""

    title: str
    description: str
    subject_ids: tuple[UUID, ...]
    topic_ids: tuple[UUID, ...]
    years_of_study: tuple[int, ...]
    type: ItemType
    language: ItemLanguage
    licence: MaterialLicence
    attested: bool
    body_md: str | None = None


@dataclass(frozen=True, slots=True)
class MaterialPatch:
    """The fields an owner may change; None leaves a field alone.

    `attested` only changes while the material is a draft or sent back.
    """

    title: str | None = None
    description: str | None = None
    topic_ids: tuple[UUID, ...] | None = None
    body_md: str | None = None
    attested: bool | None = None
