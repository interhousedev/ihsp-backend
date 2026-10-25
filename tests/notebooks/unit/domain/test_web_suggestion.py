"""Web search suggestion: when sources are thin, and the query from the topic."""

from app.modules.notebooks.domain.web_suggestion import (
    QUERY_MAX_CHARS,
    is_thin_sources,
    suggestion_for_content,
    suggestion_for_request,
    web_search_query,
)


def test_no_sources_is_thin() -> None:
    """No source at all always suggests a search, whatever the threshold."""
    assert is_thin_sources(0, 0, threshold=0) is True


def test_text_below_the_threshold_is_thin_and_at_it_is_not() -> None:
    """Strictly below the threshold counts as thin."""
    assert is_thin_sources(5_999, 2, threshold=6_000) is True
    assert is_thin_sources(6_000, 2, threshold=6_000) is False


def test_request_suggests_the_topic_query_only_when_thin() -> None:
    """The query is the title plus the focus; nothing when the sources are enough."""
    thin = suggestion_for_request(
        char_counts=[120, 300], title="Biology", focus="cell division", threshold=6_000
    )
    full = suggestion_for_request(
        char_counts=[4_000, 4_000],
        title="Biology",
        focus="cell division",
        threshold=6_000,
    )
    assert thin == "Biology cell division"
    assert full is None


def test_request_without_sources_suggests_a_search() -> None:
    """A request made without sources gets the suggestion from the title alone."""
    assert (
        suggestion_for_request(
            char_counts=[], title="Algebra", focus=None, threshold=6_000
        )
        == "Algebra"
    )


def test_query_is_collapsed_and_capped() -> None:
    """Whitespace is collapsed and the query stays within the length cap."""
    query = web_search_query("  Physics\n\n  lab ", "x " * 500)
    assert query is not None
    assert "  " not in query and "\n" not in query
    assert len(query) <= QUERY_MAX_CHARS


def test_empty_topic_gives_no_query() -> None:
    """Without a title or a focus there is nothing to search for."""
    assert web_search_query(None, "  ") is None
    assert (
        suggestion_for_request(char_counts=[], title="", focus=None, threshold=6_000)
        is None
    )


def test_unverified_content_suggests_a_search() -> None:
    """The faithfulness check left claims unsupported by the sources."""
    content = {"verification": {"status": "unverified", "unsupported": ["x"]}}
    query = suggestion_for_content(
        content,
        verification_key="verification",
        unverified="unverified",
        title="Biology",
        focus=None,
    )
    assert query == "Biology"


def test_verified_or_missing_content_suggests_nothing() -> None:
    """A verified output, or one without the mark, offers no search."""
    kwargs = {
        "verification_key": "verification",
        "unverified": "unverified",
        "title": "Biology",
        "focus": None,
    }
    assert suggestion_for_content(None, **kwargs) is None
    assert suggestion_for_content({"verification": {"status": "ok"}}, **kwargs) is None
