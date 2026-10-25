"""Canonical JSON and hashes of course drafts."""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:  # noqa: ANN401 - any JSON-compatible value
    """Serialize JSON-compatible data with sorted keys and no whitespace."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def outline_hash(meta: dict[str, Any], outline: dict[str, Any]) -> str:
    """Hash of the draft meta (title, description) and the draft outline."""
    payload = canonical_json({"meta": meta, "outline": outline})
    return hashlib.sha256(payload.encode()).hexdigest()
