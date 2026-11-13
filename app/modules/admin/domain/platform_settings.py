"""Runtime platform settings Administration may change without a deploy."""

from dataclasses import dataclass, replace
from typing import Any

from app.shared.base_error import ValidationFailedError
from app.shared.contracts.honours import (
    HONOURS_MAX_FOURS_LIMIT,
    FlagRule,
    HonoursRules,
    MaxFoursRule,
    SerialsRule,
)

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
    honours: HonoursRules = HonoursRules()

    def as_stored(self) -> dict[str, Any]:
        """One JSON value per key, as kept in ``admin.platform_settings``."""
        return {
            "school_name": self.school_name,
            "support_contact": self.support_contact,
            "change_password_on_login": self.change_password_on_login,
            "default_language": self.default_language,
            "honours": self.honours.as_stored(),
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
    cleaned = {key: _clean(key, value) for key, value in changes.items()}
    return replace(current, **cleaned)


def _clean(key: str, value: Any) -> Any:
    if key == "school_name":
        return _text(key, value, SCHOOL_NAME_MAX_LENGTH)
    if key == "support_contact":
        return _text(key, value, SUPPORT_CONTACT_MAX_LENGTH)
    if key == "change_password_on_login" and isinstance(value, bool):
        return value
    if key == "default_language" and value in LOCALES:
        return value
    if key == "honours":
        return parse_honours(value)
    raise PlatformSettingsInvalidError(params={"field": key})


def _text(key: str, value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise PlatformSettingsInvalidError(params={"field": key})
    return value.strip()


def _honours_field(value: Any, name: str) -> dict[str, Any]:
    rule = value.get(name) if isinstance(value, dict) else None
    if not isinstance(rule, dict) or not isinstance(rule.get("enabled"), bool):
        raise PlatformSettingsInvalidError(params={"field": f"honours.{name}"})
    return rule


def _max_fours(value: Any, name: str) -> MaxFoursRule:
    rule = _honours_field(value, name)
    limit = rule.get("max")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 0 <= limit <= HONOURS_MAX_FOURS_LIMIT
    ):
        raise PlatformSettingsInvalidError(params={"field": f"honours.{name}.max"})
    return MaxFoursRule(rule["enabled"], limit)


def _serials(value: Any, name: str) -> SerialsRule:
    rule = _honours_field(value, name)
    serials = rule.get("serials")
    if (
        not isinstance(serials, list)
        or not all(isinstance(s, str) and s.strip() for s in serials)
        or (rule["enabled"] and not serials)
    ):
        raise PlatformSettingsInvalidError(params={"field": f"honours.{name}.serials"})
    return SerialsRule(rule["enabled"], tuple(s.strip() for s in serials))


def parse_honours(value: Any) -> HonoursRules:
    """Validate the ``honours`` value (the shape of `HonoursRules.as_stored`)."""
    return HonoursRules(
        red_diploma_max_fours=_max_fours(value, "red_diploma_max_fours"),
        medal_certificate=_serials(value, "medal_certificate"),
        gold_controls_all_five=FlagRule(
            _honours_field(value, "gold_controls_all_five")["enabled"]
        ),
        gold_semester_all_five=FlagRule(
            _honours_field(value, "gold_semester_all_five")["enabled"]
        ),
        silver_controls_all_five=FlagRule(
            _honours_field(value, "silver_controls_all_five")["enabled"]
        ),
        silver_semester_max_fours=_max_fours(value, "silver_semester_max_fours"),
    )
