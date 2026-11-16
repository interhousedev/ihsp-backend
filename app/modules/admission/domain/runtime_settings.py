"""Admin-editable admission settings stored in `admission.runtime_settings`."""

from dataclasses import dataclass
from typing import Any, Final

PICKUP_LOCATION: Final = "pickup_location"
ESTIMATES_STUDENT_VISIBLE: Final = "estimates_student_visible"
WELLBEING_QUESTIONS: Final = "wellbeing_questions_enabled"
KNOWN_KEYS: Final = frozenset(
    {PICKUP_LOCATION, ESTIMATES_STUDENT_VISIBLE, WELLBEING_QUESTIONS}
)


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
