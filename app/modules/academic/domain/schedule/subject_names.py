"""Translating the missing languages of a subject name (one small model call)."""

import json
from collections.abc import Mapping
from typing import Any, Final

from app.modules.academic.domain.schedule.subject import LANGUAGES

SCHEMA_NAME: Final = "subject_names"
LANGUAGE_NAMES: Final = {"uz": "Uzbek (Latin)", "ru": "Russian", "en": "English"}
SYSTEM_PROMPT: Final = (
    "You translate the name of a school subject. The user sends JSON with `known` "
    "(the names that exist, by language code) and `missing` (the codes to produce). "
    "Reply with a JSON object with the keys uz, ru and en: put the translated name "
    "under every code in `missing` and an empty string under the others. Use the "
    "usual short school name of the subject, with no quotes or explanation. "
    "Languages: "
    + "; ".join(f"{code} = {name}" for code, name in LANGUAGE_NAMES.items())
)
SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {code: {"type": "string"} for code in LANGUAGES},
    "required": list(LANGUAGES),
    "additionalProperties": False,
}


def known_names(names: Mapping[str, str]) -> dict[str, str]:
    """The non-empty names of the three languages."""
    return {
        code: value.strip()
        for code in LANGUAGES
        if (value := (names.get(code) or "").strip())
    }


def missing_locales(names: Mapping[str, str]) -> list[str]:
    """The languages without a name; none when no name is known at all."""
    known = known_names(names)
    if not known:
        return []
    return [code for code in LANGUAGES if code not in known]


def request_message(names: Mapping[str, str]) -> str:
    """The user message: the known names and the codes to translate."""
    return json.dumps(
        {"known": known_names(names), "missing": missing_locales(names)},
        ensure_ascii=False,
    )


def parse_translation(data: Mapping[str, Any], wanted: list[str]) -> dict[str, str]:
    """Keep only the wanted languages that came back as a non-empty string."""
    found: dict[str, str] = {}
    for code in wanted:
        value = data.get(code)
        if isinstance(value, str) and value.strip():
            found[code] = value.strip()
    return found
