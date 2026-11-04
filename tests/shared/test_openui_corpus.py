"""AI-OPENUI: the shared corpus of valid and invalid blocks and fences.

The web (`packages/features-core/src/openui`) runs the same `corpus.json` through its
own renderability check, so the two sides cannot drift apart silently.
"""

import json
from pathlib import Path
from typing import Any

from app.shared.openui.blocks import split_blocks
from app.shared.openui.validate import validate_block

import pytest

CORPUS = json.loads(
    (Path(__file__).resolve().parents[2] / "app/shared/openui/corpus.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CORPUS["blocks"], ids=lambda c: c["name"])
def test_corpus_block_is_valid_or_invalid_as_labelled(case: dict[str, Any]) -> None:
    """AI-OPENUI: the backend validator agrees with the label of every corpus block."""
    errors = validate_block(case["source"], case["subset"])
    assert (errors == []) is case["valid"], errors


@pytest.mark.parametrize("case", CORPUS["fences"], ids=lambda c: c["name"])
def test_corpus_fence_splits_as_labelled(case: dict[str, Any]) -> None:
    """AI-OPENUI: a fence indented up to three spaces is a block, four is text."""
    parts = split_blocks(case["text"])
    assert sum(part.kind == "block" for part in parts) == case["blocks"]
    assert sum(part.kind == "pending" for part in parts) == case["pending"]
