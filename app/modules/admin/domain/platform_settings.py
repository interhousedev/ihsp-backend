"""Runtime platform settings Administration may change without a deploy."""

from dataclasses import dataclass, replace
from typing import Any

from app.shared.base_error import ValidationFailedError

LOCALES = ("uz", "ru", "en")
SCHOOL_NAME_MAX_LENGTH = 120
SUPPORT_CONTACT_MAX_LENGTH = 255


class PlatformSettingsInvalidError(ValidationFailedError):
    """A platform setting has an invalid value."""

    code = "admin/platform-settings-invalid"
    message_key = "admin-platform-settings-invalid"


@dataclass(frozen=True, slots=True)
class PlatformSettings:
    """The editable settings with their defaults (a key never saved uses these)."""

    school_name: str = ""
    support_contact: str = ""
    change_password_on_login: bool = False
    default_language: str = "ru"

    def as_stored(self) -> dict[str, Any]:
        """One JSON value per key, as kept in ``admin.platform_settings``."""
        return {
            "school_name": self.school_name,
            "support_contact": self.support_contact,
            "change_password_on_login": self.change_password_on_login,
            "default_language": self.default_language,
        }


KEYS = frozenset(PlatformSettings().as_stored())


def from_stored(values: dict[str, Any]) -> PlatformSettings:
    """Build the settings from stored rows; unknown or broken values are ignored."""
    base = PlatformSettings()
    try:
        return apply_changes(base, values)
    except PlatformSettingsInvalidError:
        good = {k: v for k, v in values.items() if _valid(base, k, v)}
        return apply_changes(base, good)


def _valid(base: PlatformSettings, key: str, value: Any) -> bool:
    try:
        apply_changes(base, {key: value})
    except PlatformSettingsInvalidError:
        return False
    return True


def apply_changes(
    current: PlatformSettings, changes: dict[str, Any]
) -> PlatformSettings:
    """Validate the given keys and return the updated settings.

    Raises `PlatformSettingsInvalidError` (params: ``field``) for an unknown key, a
    wrong type, a too long text or an unsupported language.
    """
    cleaned: dict[str, Any] = {}
    for key, value in changes.items():
        if key == "school_name":
            cleaned[key] = _text(key, value, SCHOOL_NAME_MAX_LENGTH)
        elif key == "support_contact":
            cleaned[key] = _text(key, value, SUPPORT_CONTACT_MAX_LENGTH)
        elif key == "change_password_on_login":
            if not isinstance(value, bool):
                raise PlatformSettingsInvalidError(params={"field": key})
            cleaned[key] = value
        elif key == "default_language":
            if value not in LOCALES:
                raise PlatformSettingsInvalidError(params={"field": key})
            cleaned[key] = value
        else:
            raise PlatformSettingsInvalidError(params={"field": key})
    return replace(current, **cleaned)


def _text(key: str, value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise PlatformSettingsInvalidError(params={"field": key})
    return value.strip()
