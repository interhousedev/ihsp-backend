"""NB-14: a passage text has one stable identity."""

import hashlib

from app.modules.notebooks.domain.passage_hash import passage_hash

from hypothesis import given
from hypothesis import strategies as st


def test_the_hash_is_the_sha256_of_the_utf8_text() -> None:
    """NB-14: the migration computes the same value in SQL."""
    text = "В фотосинтезе растения используют свет."

    assert passage_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert len(passage_hash(text)) == 64


def test_different_texts_have_different_hashes() -> None:
    """NB-14: a changed passage does not reuse the vector of the old one."""
    assert passage_hash("Cell wall.") != passage_hash("Cell wall. ")


@given(st.text())
def test_the_hash_of_a_text_never_changes(text: str) -> None:
    """NB-14: equal texts in different documents share their derived values."""
    assert passage_hash(text) == passage_hash(str(text))
