"""NB-AUTO: when two students ask for the same Studio output."""

from typing import Any

from app.modules.notebooks.domain.artifacts.cache_key import artifact_cache_key

from hypothesis import given
from hypothesis import strategies as st


def key(**changes: Any) -> str:
    """The key of a quiz of two texts, with `changes` applied."""
    values: dict[str, Any] = {
        "kind": "quiz",
        "report_format": None,
        "options": {"count": 10, "language": None, "source_ids": ["x"]},
        "content_hashes": ["a" * 64, "b" * 64],
        "language": "en",
    }
    values.update(changes)
    return artifact_cache_key(**values)


def test_the_same_request_has_the_same_key() -> None:
    """NB-AUTO: a key is a hash of the request, 64 hex characters."""
    assert key() == key()
    assert len(key()) == 64


def test_the_order_of_the_texts_does_not_matter() -> None:
    """NB-AUTO: two students who ticked the same files in another order share."""
    assert key(content_hashes=["b" * 64, "a" * 64]) == key()


def test_the_students_own_source_rows_and_auto_language_do_not_matter() -> None:
    """NB-AUTO: source ids and the "auto" language do not change the result."""
    other = {"count": 10, "language": "en", "source_ids": ["y", "z"]}

    assert key(options=other) == key()


def test_everything_that_changes_the_output_changes_the_key() -> None:
    """NB-AUTO: kind, format, options, texts and language each give another key."""
    base = key()

    assert key(kind="report") != base
    assert key(report_format="faq") != base
    assert key(options={"count": 20}) != base
    assert key(content_hashes=["a" * 64]) != base
    assert key(language="ru") != base


HASH = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


@given(st.lists(HASH, min_size=1, max_size=6, unique=True), st.randoms())
def test_any_order_of_the_same_texts_gives_the_same_key(
    hashes: list[str], rng: Any
) -> None:
    """NB-AUTO: the key names a set of texts, not the order they were ticked in."""
    shuffled = list(hashes)
    rng.shuffle(shuffled)

    assert key(content_hashes=shuffled) == key(content_hashes=hashes)
