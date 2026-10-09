"""Helpers of the UniLibrary tests: recorded fixtures and request counting."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "library" / "unilibrary"


def load(name: str) -> Any:  # noqa: ANN401 - fixtures are arbitrary JSON
    """The JSON of a recorded UniLibrary response (`list_page`, `detail`, ...)."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
