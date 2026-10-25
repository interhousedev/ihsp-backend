"""Subjects with names in three languages."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.domain.schedule.errors import SubjectNameInvalidError

LANGUAGES = ("uz", "ru", "en")


@dataclass(slots=True)
class Subject:
    """A subject; EMIS often leaves one language empty."""

    id: UUID
    name: dict[str, str] = field(default_factory=dict)
    short_name: str | None = None
    emis_subject_id: int | None = None
    can_be_divided: bool = False


def subject_name(subject: Subject, locale: str) -> str:
    """Return the name in the locale, falling back uz, ru, en."""
    for language in (locale, *LANGUAGES):
        value = subject.name.get(language, "").strip()
        if value:
            return value
    return subject.short_name or ""


def clean_names(raw: dict[str, str]) -> dict[str, str]:
    """Keep the three languages, strip them, and require at least one name."""
    names = {lang: (raw.get(lang) or "").strip() for lang in LANGUAGES}
    if not any(names.values()):
        raise SubjectNameInvalidError()
    return names
