"""Admin-editable admission settings stored in `admission.runtime_settings`."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final

PICKUP_LOCATION: Final = "pickup_location"
ESTIMATES_STUDENT_VISIBLE: Final = "estimates_student_visible"
WELLBEING_QUESTIONS: Final = "wellbeing_questions_enabled"
CALENDAR_ALARM_OFFSETS: Final = "calendar_alarm_offsets_days"
READINESS_WEIGHTS: Final = "readiness_weights"
# The school grades the lyceum teaches, e.g. [10, 11]: who is entitled and which
# grades a student plans activities for. The environment gives the default.
SCHOOL_GRADES: Final = "school_grades"
# Link template of "open on a map" (https, one `{query}` placeholder).
MAPS_URL_TEMPLATE: Final = "maps_url_template"
SCHOOL_GRADE_MIN: Final = 1
SCHOOL_GRADE_MAX: Final = 12
KNOWN_KEYS: Final = frozenset(
    {
        PICKUP_LOCATION,
        ESTIMATES_STUDENT_VISIBLE,
        WELLBEING_QUESTIONS,
        CALENDAR_ALARM_OFFSETS,
        READINESS_WEIGHTS,
        SCHOOL_GRADES,
        MAPS_URL_TEMPLATE,
    }
)


def valid_school_grades(value: object) -> tuple[int, ...] | None:
    """Return a non-empty contiguous ascending range of grades 1–12, or None."""
    if not isinstance(value, list | tuple) or not value:
        return None
    if any(isinstance(g, bool) or not isinstance(g, int) for g in value):
        return None
    grades = tuple(sorted(set(value)))
    if grades[0] < SCHOOL_GRADE_MIN or grades[-1] > SCHOOL_GRADE_MAX:
        return None
    if grades != tuple(range(grades[0], grades[-1] + 1)):
        return None
    return grades


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """A snapshot of stored values; missing keys fall back to the environment."""

    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Return the stored value or the default."""
        return self.values.get(key, default)

    def pickup_location(self) -> dict[str, str] | None:
        """Return the transcript pickup location per locale, or None if unset."""
        value = self.values.get(PICKUP_LOCATION)
        return value if isinstance(value, dict) and value else None

    def maps_url_template(self) -> str | None:
        """Return the stored map link template, or None for the default."""
        value = self.values.get(MAPS_URL_TEMPLATE)
        return value if isinstance(value, str) and value else None

    def school_grades(self, default: Collection[int]) -> tuple[int, ...]:
        """Return the stored school grades, else the environment default."""
        stored = valid_school_grades(self.values.get(SCHOOL_GRADES))
        return stored if stored is not None else tuple(sorted(default))
