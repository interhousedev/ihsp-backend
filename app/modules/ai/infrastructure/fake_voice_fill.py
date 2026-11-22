"""Deterministic fake document for the admission voice fill."""

import re
from collections.abc import Sequence
from typing import Any

VOICE_FILL_SCHEMA = "voice_fill"

_FIELD = re.compile(r"\[field ([a-z0-9_]+)\] .*?\(kind: (\w+)(?:; options: ([^)]*))?\)")
_TRANSCRIPT = re.compile(r"\[transcript\] (.*)")


def build_voice_fill_document(
    schema_name: str, messages: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Deterministic voice-fill answer, or None for other schemas.

    The first text field gets the transcript, numbers 2, choices the first option;
    any later text field stays empty.
    """
    if schema_name != VOICE_FILL_SCHEMA:
        return None
    text = "\n".join(str(m.get("content", "")) for m in messages)
    spoken = _TRANSCRIPT.search(text)
    said = spoken.group(1).strip() if spoken else ""
    values: list[dict[str, str]] = []
    first_text = True
    for key, kind, options in _FIELD.findall(text):
        if kind == "number":
            value = "2"
        elif kind == "choice":
            value = options.split(" | ")[0].strip()
        elif first_text:
            value, first_text = said, False
        else:
            value = ""
        values.append({"key": key, "value": value})
    return {"values": values}
