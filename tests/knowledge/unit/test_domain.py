"""KB-01: key, title, value and tag rules of a knowledge entry."""

from app.modules.knowledge.domain.entry import (
    normalize_key,
    normalize_tags,
    normalize_title,
    normalize_value,
    text_hash,
)
from app.modules.knowledge.domain.errors import KnowledgeInvalidError

import pytest


def test_key_is_trimmed_collapsed_and_lower_cased() -> None:
    """KB-01: keys ignore case and extra spaces."""
    assert normalize_key("  Wi-Fi   Password ") == "wi-fi password"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 81])
def test_bad_key_is_rejected(raw: str) -> None:
    """KB-01: an empty or too long key is invalid."""
    with pytest.raises(KnowledgeInvalidError):
        normalize_key(raw)


def test_title_and_value_rules() -> None:
    """KB-01: an empty title means none; an empty value is invalid."""
    assert normalize_title("  ") is None
    assert normalize_title(" A  B ") == "A B"
    with pytest.raises(KnowledgeInvalidError):
        normalize_value("  ")


def test_tags_are_lower_cased_and_unique() -> None:
    """KB-01: tags keep their order without repeats."""
    assert normalize_tags(["Rules", "exams", " rules "]) == ["rules", "exams"]
    with pytest.raises(KnowledgeInvalidError):
        normalize_tags(["ok", ""])


def test_text_hash_is_sha256_hex() -> None:
    """KB-01: the vector key is a 64 character hex digest."""
    assert len(text_hash("a")) == 64
