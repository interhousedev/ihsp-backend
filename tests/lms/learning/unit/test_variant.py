"""LMS-16, LMS-17: attempt variants are stable per attempt and respect the settings."""

from uuid import UUID

from app.modules.lms.domain.learning.variant import Variant, build_variant, max_score_of
from app.shared.ids import new_id
from tests.lms.learning.builders import choice, quiz

from hypothesis import given
from hypothesis import strategies as st

ATTEMPT = UUID("0192f3c4-0000-7000-8000-000000000001")


def ten_questions() -> list:
    """Ten single choice questions with four options each."""
    return [
        choice(f"q{i}", correct=["a"], options=("a", "b", "c", "d")) for i in range(10)
    ]


def test_the_variant_is_the_same_every_time_for_one_attempt() -> None:
    """LMS-17: reloading the page must not reshuffle."""
    test = quiz(questions=ten_questions(), shuffle_questions=True, shuffle_options=True)

    first = build_variant(test, ATTEMPT)
    second = build_variant(test, ATTEMPT)

    assert first == second


def test_two_attempts_get_different_orders() -> None:
    """LMS-16: shuffling makes attempts differ."""
    test = quiz(questions=ten_questions(), shuffle_questions=True, shuffle_options=True)

    variants = {build_variant(test, new_id()).question_ids for _ in range(5)}

    assert len(variants) > 1


def test_without_shuffling_the_original_order_is_kept() -> None:
    """LMS-16: shuffles are opt-in."""
    test = quiz(questions=ten_questions())

    variant = build_variant(test, ATTEMPT)

    assert variant.question_ids == tuple(f"q{i}" for i in range(10))
    assert variant.option_order["q3"] == ["q3-a", "q3-b", "q3-c", "q3-d"]


def test_a_pool_of_five_from_ten_picks_five_distinct_questions() -> None:
    """LMS-16: N of M questions per attempt."""
    test = quiz(questions=ten_questions(), pool_size=5)

    variant = build_variant(test, ATTEMPT)

    assert len(variant.question_ids) == 5
    assert len(set(variant.question_ids)) == 5
    assert list(variant.question_ids) == sorted(
        variant.question_ids, key=lambda q: int(q[1:])
    )


def test_a_pool_larger_than_the_test_takes_every_question() -> None:
    """LMS-16: a pool bigger than the question list is not an error."""
    test = quiz(questions=ten_questions(), pool_size=50)

    assert len(build_variant(test, ATTEMPT).question_ids) == 10


def test_pools_of_different_attempts_differ() -> None:
    """LMS-16: the pool is random per attempt."""
    test = quiz(questions=ten_questions(), pool_size=5)

    pools = {frozenset(build_variant(test, new_id()).question_ids) for _ in range(8)}

    assert len(pools) > 1


def test_pinned_options_keep_their_original_position() -> None:
    """LMS-16: 'None of the above' stays last."""
    question = choice(
        "q1", correct=["a"], options=("a", "b", "c", "none"), pinned=["none"]
    )
    test = quiz(questions=[question], shuffle_options=True)

    for _ in range(20):
        order = build_variant(test, new_id()).option_order["q1"]
        assert order[-1] == "q1-none"
        assert sorted(order) == ["q1-a", "q1-b", "q1-c", "q1-none"]


def test_a_pinned_option_in_the_middle_stays_in_the_middle() -> None:
    """LMS-16: pinned means the original index, wherever it is."""
    question = choice("q1", correct=["a"], options=("a", "b", "c", "d"), pinned=["b"])
    test = quiz(questions=[question], shuffle_options=True)

    for _ in range(20):
        assert build_variant(test, new_id()).option_order["q1"][1] == "q1-b"


def test_text_and_number_questions_have_no_option_order() -> None:
    """LMS-15: only choice questions order options."""
    from tests.lms.learning.builders import number_question, text_question

    test = quiz(
        questions=[text_question("t", accepted=["x"]), number_question("n", value=1)]
    )

    assert build_variant(test, ATTEMPT).option_order == {}


def test_the_max_score_is_the_sum_of_the_picked_questions() -> None:
    """LMS-16: a pool changes the maximum."""
    questions = [choice(f"q{i}", correct=["a"], points=2.5) for i in range(4)]
    test = quiz(questions=questions, pool_size=2)

    variant = build_variant(test, ATTEMPT)

    assert str(max_score_of(test, variant)) == "5.0"


def test_a_variant_survives_the_stored_json_form() -> None:
    """LMS-17: the variant is stored with the attempt and read back."""
    test = quiz(questions=ten_questions(), shuffle_questions=True, shuffle_options=True)
    variant = build_variant(test, ATTEMPT)

    assert Variant.from_json(variant.to_json()) == variant


@given(st.uuids(version=4), st.integers(min_value=1, max_value=10))
def test_options_are_always_a_permutation_of_the_question_options(
    attempt_id: UUID, pool: int
) -> None:
    """LMS-16: shuffling never loses or duplicates an option."""
    test = quiz(
        questions=ten_questions(),
        pool_size=pool,
        shuffle_questions=True,
        shuffle_options=True,
    )

    variant = build_variant(test, attempt_id)

    assert len(variant.question_ids) == pool
    for question_id, order in variant.option_order.items():
        assert sorted(order) == [f"{question_id}-{c}" for c in "abcd"]
