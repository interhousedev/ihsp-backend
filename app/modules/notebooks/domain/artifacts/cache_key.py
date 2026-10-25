"""The key under which a finished Studio output is shared between students."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

CACHE_VERSION: Final = 1  # raise it when prompts or schemas change: old rows go unused
_PERSONAL_OPTIONS: Final = frozenset({"source_ids", "language"})


def artifact_cache_key(
    *,
    kind: str,
    report_format: str | None,
    options: Mapping[str, Any],
    content_hashes: Sequence[str],
    language: str,
) -> str:
    """sha256 of what decides the output: kind, format, options, texts and language.

    The student's own choices that do not change the result (which source rows, the
    "auto" language) are left out; the texts are named by their content hashes, so
    two students who hold the same files ask for the same thing.
    """
    options_without_personal = {
        key: value for key, value in options.items() if key not in _PERSONAL_OPTIONS
    }
    payload = {
        "v": CACHE_VERSION,
        "kind": kind,
        "format": report_format,
        "options": options_without_personal,
        "texts": sorted(content_hashes),
        "language": language,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
