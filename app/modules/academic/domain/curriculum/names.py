"""Names of curriculum subjects in the three languages."""

from collections.abc import Mapping

from app.modules.academic.domain.schedule.subject import LANGUAGES
from app.shared.contracts.emis import EmisName


def name_dict(name: EmisName) -> dict[str, str]:
    """The EMIS name as ``{"uz": ..., "ru": ..., "en": ...}`` (stored as sent)."""
    return {"uz": name.uz, "ru": name.ru, "en": name.en}


def fill_missing_names(current: Mapping[str, str], offered: EmisName) -> dict[str, str]:
    """Return ``current`` with the empty languages filled from ``offered``.

    A language counts as empty when it is missing or blank. A name that exists is
    never overwritten, and a blank offer fills nothing. The result is a new dict.
    """
    filled = dict(current)
    for language in LANGUAGES:
        if (current.get(language) or "").strip():
            continue
        offer = (getattr(offered, language) or "").strip()
        if offer:
            filled[language] = offer
    return filled


def first_names(names: list[EmisName]) -> EmisName:
    """Merge several offers of one subject: per language the first non-blank name."""
    merged = EmisName()
    for name in names:
        merged = EmisName(
            uz=merged.uz or name.uz.strip(),
            ru=merged.ru or name.ru.strip(),
            en=merged.en or name.en.strip(),
        )
    return merged


def display_name(names: Mapping[str, str]) -> str:
    """A name for sorting and logs: ru, then uz, then en."""
    for language in ("ru", "uz", "en"):
        value = (names.get(language) or "").strip()
        if value:
            return value
    return ""
