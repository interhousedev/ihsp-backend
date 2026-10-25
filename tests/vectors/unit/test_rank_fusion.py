"""NB-14: reciprocal rank fusion merges rankings by position, not by score."""

from app.shared.rank_fusion import CANDIDATES, RRF_K, reciprocal_rank_fusion


def test_a_single_ranking_comes_back_unchanged() -> None:
    """Without a second opinion the order is the one given."""
    assert reciprocal_rank_fusion([["a", "b", "c"]]) == ["a", "b", "c"]


def test_a_document_that_both_rankings_like_beats_the_top_of_one() -> None:
    """3rd and 2nd (two earnings) outrank 1st in only one list."""
    words = ["only-words", "x", "both"]
    meaning = ["only-meaning", "both", "y"]

    fused = reciprocal_rank_fusion([words, meaning])

    assert fused[0] == "both"
    assert set(fused) == {"only-words", "x", "both", "only-meaning", "y"}


def test_equal_scores_keep_the_order_of_first_appearance() -> None:
    """1st of the first list and 1st of the second list tie; the first list wins."""
    assert reciprocal_rank_fusion([["a", "b"], ["c", "d"]]) == ["a", "c", "b", "d"]


def test_nothing_in_nothing_out() -> None:
    """No rankings or empty rankings fuse to nothing."""
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_a_document_appearing_twice_in_one_ranking_counts_each_time() -> None:
    """Duplicates are the caller's problem; the sum is still well defined."""
    assert reciprocal_rank_fusion([["a", "b", "a"]]) == ["a", "b"]


def test_the_constants_are_the_documented_ones() -> None:
    """k = 60 from the paper; 24 candidates per ranking."""
    assert RRF_K == 60
    assert CANDIDATES == 24
    first, tenth = 1 / (RRF_K + 1), 1 / (RRF_K + 10)
    assert round(first / tenth, 2) == 1.15  # a flat head: rank 1 is worth 15% more
