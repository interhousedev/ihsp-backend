"""EMIS student profile response (only the fields IHSP keeps)."""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator

_LANGUAGES = ("uz", "ru", "en")


def _text(value: Any) -> Any:
    """A string; ``""``, numbers and shapes we do not know are missing or text."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return None


def _named(value: Any) -> Any:
    """A name that is a string, ``{name: ...}`` or ``{uz, ru, en}`` (first filled)."""
    if isinstance(value, dict):
        if "name" in value:
            return _named(value["name"])
        for language in _LANGUAGES:
            text = _text(value.get(language))
            if text:
                return text
        return None
    return _text(value)


def _object_or_none(value: Any) -> Any:
    """A JSON object, else missing (the block is optional and best effort)."""
    return value if isinstance(value, dict) else None


OptText = Annotated[str | None, BeforeValidator(_text)]
OptName = Annotated[str | None, BeforeValidator(_named)]


class CitizenV1DTO(BaseModel):
    """Name part of the citizen record; birth date and gender are never read."""

    first_name: str
    last_name: str
    middle_name: str | None = None


class EduGroupV1DTO(BaseModel):
    """The student's study group."""

    name: str
    curriculum_id: int | None = None
    current_semester: int | None = None
    direction: OptName = None
    speciality: OptName = None


class InstitutionNameV1DTO(BaseModel):
    """The lyceum's name in the three languages (any may be missing)."""

    uz: OptText = None
    ru: OptText = None
    en: OptText = None


class InstitutionV1DTO(BaseModel):
    """The institution block of the profile."""

    name: Annotated[InstitutionNameV1DTO | None, BeforeValidator(_object_or_none)] = (
        None
    )


class ProfileV1DTO(BaseModel):
    """The ``result`` object of the profile endpoint."""

    id: int
    citizen: CitizenV1DTO
    institution_id: int
    edu_group_id: int
    edu_group: EduGroupV1DTO
    institution: Annotated[
        InstitutionV1DTO | None, BeforeValidator(_object_or_none)
    ] = None
    school_certificate_serial: OptText = None
    school_certificate_number: OptText = None
