"""Rules every entry value must satisfy for its type."""

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.errors import CertificateInvalidError

MIN_YEAR = 1990
MAX_YEAR = 2100
MAX_TEXT = 255
PERCENT_MAX = 100.0


def clean_text(value: str | None) -> str | None:
    """Trim; an empty string means "not set"."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def check_level(kind: CertificateType, level: str | None) -> None:
    """The level must be one of the type's levels (when it lists any)."""
    if level is not None and kind.levels and level not in kind.levels:
        raise CertificateInvalidError(params={"field": "level"})


def check_score(kind: CertificateType, score: float | None) -> None:
    """The score must be within the type's range."""
    if score is None:
        return
    low, high = kind.score_min, kind.score_max
    if (low is not None and score < low) or (high is not None and score > high):
        raise CertificateInvalidError(
            params={"field": "score", "min": low, "max": high}
        )


def check_percent(percent: float | None) -> None:
    """A percent is between 0 and 100."""
    if percent is not None and not 0 <= percent <= PERCENT_MAX:
        raise CertificateInvalidError(params={"field": "percent", "min": 0, "max": 100})


def check_year(year: int | None) -> None:
    """A year is a plausible calendar year."""
    if year is not None and not MIN_YEAR <= year <= MAX_YEAR:
        raise CertificateInvalidError(
            params={"field": "year", "min": MIN_YEAR, "max": MAX_YEAR}
        )


def check_text(field_name: str, value: str | None) -> None:
    """Subject and serial are short."""
    if value is not None and len(value) > MAX_TEXT:
        raise CertificateInvalidError(params={"field": field_name, "max": MAX_TEXT})
