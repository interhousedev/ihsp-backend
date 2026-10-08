"""Loads the recorded EMIS responses from tests/fixtures/emis."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "emis"


def load_fixture(name: str) -> dict[str, Any]:
    """Return one recorded response as a dict."""
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data
