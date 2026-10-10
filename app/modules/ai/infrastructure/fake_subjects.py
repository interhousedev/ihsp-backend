"""The fake answer to the subject name translation (``subject_names`` schema)."""

import json
from collections.abc import Sequence
from typing import Any

SUBJECT_NAMES_SCHEMA = "subject_names"
LANGUAGES = ("uz", "ru", "en")


def subject_names_document(messages: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Return the first known name for every missing language, "" for the others."""
    try:
        request = json.loads(str(messages[-1].get("content", "")))
    except (IndexError, ValueError):
        request = {}
    known = [v for v in (request.get("known") or {}).values() if v]
    source = known[0] if known else ""
    missing = request.get("missing") or []
    return {code: source if code in missing else "" for code in LANGUAGES}
