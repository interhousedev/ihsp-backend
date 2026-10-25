"""Pure rules that turn a settings button press into a preferences patch."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.shared.contracts.identity import UserPreferences

LOCALES = ("uz", "ru", "en")
MARK_TYPES = ("lesson", "midterm", "final")
MARK_VALUES = (2, 3, 4, 5)
LEAD_MINUTES = (5, 10, 15)
RATING_PRESETS = ("3.5", "4.0", "4.5")
MARK_PRESETS = ("3", "4", "5")
OFF = "off"

# Which settings screen a key belongs to (it is shown again after the change).
SCREEN_OF_KEY = {
    "lang": "lang",
    "marks_enabled": "marks",
    "type": "marks",
    "value": "marks",
    "drops": "marks",
    "gpa_below": "thresholds",
    "sem_below": "thresholds",
    "mark_below": "thresholds",
    "lead": "lessons",
    "prompt": "lessons",
}

Patch = dict[str, Any]


def _toggle(current: list[Any], item: Any, order: tuple[Any, ...]) -> list[Any]:
    chosen = set(current)
    chosen.symmetric_difference_update({item})
    return [entry for entry in order if entry in chosen]


def _lang(prefs: UserPreferences, value: str) -> Patch | None:
    return {"locale": value} if value in LOCALES else None


def _marks_enabled(prefs: UserPreferences, value: str) -> Patch:
    return {"marks_enabled": value == "1"}


def _type(prefs: UserPreferences, value: str) -> Patch | None:
    if value not in MARK_TYPES:
        return None
    return {"marks_types": _toggle(list(prefs.marks_types), value, MARK_TYPES)}


def _value(prefs: UserPreferences, value: str) -> Patch | None:
    if not value.isdigit() or int(value) not in MARK_VALUES:
        return None
    return {"marks_values": _toggle(prefs.marks_values, int(value), MARK_VALUES)}


def _drops(prefs: UserPreferences, value: str) -> Patch:
    return {"alerts_drops": value == "1"}


def _rating(field: str) -> Callable[[UserPreferences, str], Patch | None]:
    def build(prefs: UserPreferences, value: str) -> Patch | None:
        if value == OFF:
            return {field: None}
        return {field: float(value)} if value in RATING_PRESETS else None

    return build


def _mark_below(prefs: UserPreferences, value: str) -> Patch | None:
    if value == OFF:
        return {"alerts_mark_below": None}
    return {"alerts_mark_below": int(value)} if value in MARK_PRESETS else None


def _lead(prefs: UserPreferences, value: str) -> Patch | None:
    if not value.isdigit() or int(value) not in LEAD_MINUTES:
        return None
    return {"lessons_links_lead_min": int(value)}


def _prompt(prefs: UserPreferences, value: str) -> Patch:
    return {"lessons_prompt_enabled": value == "1"}


_RULES: dict[str, Callable[[UserPreferences, str], Patch | None]] = {
    "lang": _lang,
    "marks_enabled": _marks_enabled,
    "type": _type,
    "value": _value,
    "drops": _drops,
    "gpa_below": _rating("alerts_gpa_below"),
    "sem_below": _rating("alerts_semester_mark_below"),
    "mark_below": _mark_below,
    "lead": _lead,
    "prompt": _prompt,
}


def preference_patch(prefs: UserPreferences, key: str, value: str) -> Patch | None:
    """Return the patch for a ``SettingsCb(key, value)`` press, or None if invalid."""
    rule = _RULES.get(key)
    return rule(prefs, value) if rule is not None else None


def subject_patch(
    prefs: UserPreferences, subject_ids: list[UUID], index: int
) -> Patch | None:
    """Toggle the subject at ``index``; None in the preference means all subjects.

    Ids are returned as strings because the patch is merged into a JSON column.
    """
    if not 0 <= index < len(subject_ids):
        return None
    current = prefs.marks_subject_ids
    chosen = set(subject_ids if current is None else current)
    chosen.symmetric_difference_update({subject_ids[index]})
    kept = [subject for subject in subject_ids if subject in chosen]
    if len(kept) == len(subject_ids):
        return {"marks_subject_ids": None}
    return {"marks_subject_ids": [str(subject) for subject in kept]}
