"""A kind of certificate students record (IELTS, CEFR, SAT, ...)."""

from dataclasses import dataclass, field
from uuid import UUID

LOCALES = ("uz", "ru", "en")


@dataclass(slots=True)
class CertificateType:
    """A type with the fields a student fills in for it."""

    id: UUID
    code: str
    name: dict[str, str]
    levels: list[str] = field(default_factory=list)
    asks_level: bool = False
    asks_score: bool = False
    score_min: float | None = None
    score_max: float | None = None
    asks_percent: bool = False
    asks_subject: bool = False
    asks_year: bool = True
    builtin: bool = False
    position: int = 0

    def title(self, locale: str) -> str:
        """The name in the locale, else English, else the code."""
        return self.name.get(locale) or self.name.get("en") or self.code


TYPE_FIELDS = (
    "code",
    "name",
    "levels",
    "asks_level",
    "asks_score",
    "score_min",
    "score_max",
    "asks_percent",
    "asks_subject",
    "asks_year",
    "position",
)
