"""NB-11, NB-17: the pure parts of the context builder (§ 3.3.2)."""

from uuid import UUID

from app.modules.notebooks.domain.context_policy import (
    allocate_tokens,
    build_pack,
    choose_chat_mode,
    choose_studio_mode,
    evenly_spaced,
    expand_with_neighbours,
    retrieval_query,
)
from app.modules.notebooks.domain.entities import Passage, Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.tokens import estimate_tokens
from app.shared.ids import new_id
from tests.notebooks.unit.domain.pack_builder import make_passage, make_source

from hypothesis import given, settings
from hypothesis import strategies as st


def passages_of(source: Source, count: int, tokens: int = 10) -> list[Passage]:
    return [
        make_passage(source.id, seq, f"text {seq}", tokens=tokens)
        for seq in range(1, count + 1)
    ]


def seqs(passages: list[Passage]) -> list[int]:
    return [p.seq for p in passages]


# - - - build_pack - - -


def test_pack_labels_passages_by_source_position_and_seq() -> None:
    first, second = make_source("Biology"), make_source("Notes")
    by_source = {first.id: passages_of(first, 2), second.id: passages_of(second, 1)}

    pack = build_pack([first, second], by_source, "full")

    assert list(pack.labels) == ["S1:P1", "S1:P2", "S2:P1"]
    assert [s.n for s in pack.sources] == [1, 2]
    assert pack.labels["S2:P1"].passage_id == by_source[second.id][0].id


def test_pack_maps_source_labels_to_ids_and_ids_to_titles() -> None:
    first = make_source("Biology", SourceKind.FILE)
    second = make_source("My note", SourceKind.NOTE)

    pack = build_pack([first, second], {}, "full")

    assert pack.source_map == {"S1": first.id, "S2": second.id}
    assert pack.titles == {
        first.id: ("Biology", SourceKind.FILE),
        second.id: ("My note", SourceKind.NOTE),
    }


def test_pack_orders_passages_by_seq_whatever_the_input_order() -> None:
    source = make_source()
    shuffled = list(reversed(passages_of(source, 4)))

    pack = build_pack([source], {source.id: shuffled}, "full")

    assert [p.seq for p in pack.sources[0].passages] == [1, 2, 3, 4]


def test_pack_keeps_the_position_of_a_source_without_passages() -> None:
    first, second, third = make_source("A"), make_source("B"), make_source("C")
    by_source = {first.id: passages_of(first, 1), third.id: passages_of(third, 1)}

    pack = build_pack([first, second, third], by_source, "retrieval")

    assert "S3:P1" in pack.labels
    assert pack.sources[1].passages == ()


def test_pack_copies_page_heading_and_text() -> None:
    source = make_source()
    passage = make_passage(source.id, 3, "Body", page=7, heading="Intro", tokens=4)

    pack = build_pack([source], {source.id: [passage]}, "full")

    packed = pack.labels["S1:P3"]
    assert (packed.text, packed.page, packed.heading) == ("Body", 7, "Intro")
    assert (packed.source_id, packed.seq, packed.token_estimate) == (source.id, 3, 4)


def test_pack_estimates_tokens_from_its_passages() -> None:
    source = make_source()
    by_source = {source.id: passages_of(source, 3, tokens=25)}

    assert build_pack([source], by_source, "full").token_estimate == 75


def test_pack_remembers_the_mode() -> None:
    source = make_source()

    assert build_pack([source], {}, "full").retrieval is False
    assert build_pack([source], {}, "retrieval").retrieval is True
    assert build_pack([source], {}, "sample").sampled is True


def test_pack_adds_guides_only_when_asked_and_only_for_contributing_sources() -> None:
    with_guide = make_source("A", guide="About A")
    without_passages = make_source("B", guide="About B")
    by_source = {with_guide.id: passages_of(with_guide, 1)}

    plain = build_pack([with_guide, without_passages], by_source, "retrieval")
    guided = build_pack(
        [with_guide, without_passages], by_source, "retrieval", guides=True
    )

    assert [s.guide_summary for s in plain.sources] == [None, None]
    assert [s.guide_summary for s in guided.sources] == ["About A", None]
    assert guided.token_estimate > plain.token_estimate


def test_pack_ignores_an_empty_guide() -> None:
    source = make_source(guide="")

    pack = build_pack(
        [source], {source.id: passages_of(source, 1)}, "retrieval", guides=True
    )

    assert pack.sources[0].guide_summary is None


def test_pack_of_no_sources_is_empty() -> None:
    pack = build_pack([], {}, "full")

    assert (pack.sources, pack.labels, pack.source_map, pack.token_estimate) == (
        (),
        {},
        {},
        0,
    )


# - - - modes - - -


def test_chat_uses_the_full_context_up_to_the_cap() -> None:
    assert choose_chat_mode(0, 80_000) == "full"
    assert choose_chat_mode(80_000, 80_000) == "full"


def test_chat_retrieves_above_the_cap() -> None:
    assert choose_chat_mode(80_001, 80_000) == "retrieval"


def test_studio_uses_the_full_context_up_to_the_cap() -> None:
    assert choose_studio_mode(150_000, 150_000) == "full"


def test_studio_samples_above_the_cap() -> None:
    assert choose_studio_mode(150_001, 150_000) == "sample"


# - - - retrieval query - - -


def test_a_short_follow_up_gets_the_previous_question_appended() -> None:
    assert retrieval_query("and why?", "How does photosynthesis work?") == (
        "and why? How does photosynthesis work?"
    )


def test_a_long_question_is_used_alone() -> None:
    question = "Explain in detail how the light reactions produce ATP in plants"

    assert retrieval_query(question, "earlier question") == question


def test_the_length_threshold_is_forty_characters() -> None:
    thirty_nine, forty = "x" * 39, "x" * 40

    assert retrieval_query(thirty_nine, "prev") == thirty_nine + " prev"
    assert retrieval_query(forty, "prev") == forty


def test_a_short_question_without_history_is_used_alone() -> None:
    assert retrieval_query("why?", None) == "why?"
    assert retrieval_query("why?", "  ") == "why?"


def test_the_question_is_stripped() -> None:
    assert retrieval_query("  why?  \n", None) == "why?"


def test_a_very_long_previous_question_is_cut() -> None:
    query = retrieval_query("why?", "p" * 4000)

    assert query == "why? " + "p" * 500


# - - - neighbours - - -


def one_source(count: int) -> tuple[Source, list[Passage], dict[UUID, list[Passage]]]:
    source = make_source()
    passages = passages_of(source, count)
    return source, passages, {source.id: passages}


def test_hits_get_their_previous_and_next_passage() -> None:
    _, passages, by_source = one_source(10)

    result = expand_with_neighbours(by_source, [passages[4]])

    assert seqs(result) == [4, 5, 6]


def test_the_radius_widens_the_neighbourhood() -> None:
    _, passages, by_source = one_source(10)

    result = expand_with_neighbours(by_source, [passages[4]], radius=2)

    assert seqs(result) == [3, 4, 5, 6, 7]


def test_a_radius_of_zero_keeps_only_the_hits() -> None:
    _, passages, by_source = one_source(10)

    assert seqs(expand_with_neighbours(by_source, [passages[4]], radius=0)) == [5]


def test_neighbours_stop_at_the_edges_of_the_source() -> None:
    _, passages, by_source = one_source(5)

    result = expand_with_neighbours(by_source, [passages[0], passages[4]])

    assert seqs(result) == [1, 2, 4, 5]


def test_overlapping_neighbourhoods_are_not_duplicated() -> None:
    _, passages, by_source = one_source(10)

    result = expand_with_neighbours(by_source, [passages[3], passages[5]])

    assert seqs(result) == [3, 4, 5, 6, 7]


def test_a_hit_that_is_also_a_neighbour_is_kept_once() -> None:
    _, passages, by_source = one_source(10)

    result = expand_with_neighbours(by_source, [passages[4], passages[5]])

    assert seqs(result) == [4, 5, 6, 7]


def test_result_is_ordered_by_source_then_seq_whatever_the_rank() -> None:
    first, second = make_source("A"), make_source("B")
    by_source = {first.id: passages_of(first, 6), second.id: passages_of(second, 6)}
    hits = [by_source[second.id][2], by_source[first.id][4], by_source[first.id][0]]

    result = expand_with_neighbours(by_source, hits, radius=0)

    assert [(p.source_id, p.seq) for p in result] == [
        (first.id, 1),
        (first.id, 5),
        (second.id, 3),
    ]


def test_neighbours_do_not_cross_into_another_source() -> None:
    first, second = make_source("A"), make_source("B")
    by_source = {first.id: passages_of(first, 3), second.id: passages_of(second, 3)}

    result = expand_with_neighbours(by_source, [by_source[first.id][2]])

    assert {p.source_id for p in result} == {first.id}


def test_the_cap_drops_the_lowest_ranked_hits_first() -> None:
    _, passages, by_source = one_source(60)
    hits = [passages[i] for i in (50, 10, 30, 20, 40)]

    result = expand_with_neighbours(by_source, hits, max_passages=3, radius=0)

    assert seqs(result) == [11, 31, 51]


def test_the_cap_keeps_hits_before_the_neighbours_of_lower_hits() -> None:
    _, passages, by_source = one_source(40)

    result = expand_with_neighbours(
        by_source, [passages[9], passages[19]], max_passages=4
    )

    assert seqs(result) == [9, 10, 11, 20]


def test_the_default_cap_is_forty_passages() -> None:
    _, passages, by_source = one_source(200)

    result = expand_with_neighbours(by_source, passages[::3][:50])

    assert len(result) == 40


def test_pinned_passages_are_always_kept() -> None:
    _, passages, by_source = one_source(40)
    pinned = [passages[30]]

    result = expand_with_neighbours(
        by_source, [passages[i] for i in range(0, 20)], max_passages=5, pinned=pinned
    )

    assert 31 in seqs(result)
    assert len(result) == 5


def test_pinned_passages_stay_even_above_the_cap() -> None:
    _, passages, by_source = one_source(40)
    pinned = passages[10:20]

    result = expand_with_neighbours(
        by_source, [passages[0], passages[1]], max_passages=4, pinned=pinned
    )

    assert seqs(result) == list(range(11, 21))


def test_neighbours_of_pinned_passages_are_added_while_there_is_room() -> None:
    _, passages, by_source = one_source(40)

    result = expand_with_neighbours(by_source, [], pinned=[passages[20]])

    assert seqs(result) == [20, 21, 22]


def test_a_pinned_hit_is_not_duplicated() -> None:
    _, passages, by_source = one_source(10)

    result = expand_with_neighbours(
        by_source, [passages[4]], pinned=[passages[4]], radius=0
    )

    assert seqs(result) == [5]


def test_no_hits_and_no_pins_give_nothing() -> None:
    _, _, by_source = one_source(5)

    assert expand_with_neighbours(by_source, []) == []


# - - - token allocation - - -


def test_tokens_are_shared_in_proportion_to_size() -> None:
    big, small = new_id(), new_id()

    shares = allocate_tokens({big: 60_000, small: 20_000}, budget=40_000)

    assert shares == {big: 30_000, small: 10_000}


def test_every_source_gets_at_least_the_minimum() -> None:
    big, small = new_id(), new_id()

    shares = allocate_tokens({big: 100_000, small: 5_000}, budget=10_000)

    assert shares[small] == 2_000
    assert shares[big] == 9_523


def test_a_source_smaller_than_the_minimum_gets_its_own_size() -> None:
    big, tiny = new_id(), new_id()

    shares = allocate_tokens({big: 100_000, tiny: 700}, budget=10_000)

    assert shares[tiny] == 700


def test_no_source_gets_more_than_its_own_size() -> None:
    first, second = new_id(), new_id()

    shares = allocate_tokens({first: 1_000, second: 3_000}, budget=1_000_000)

    assert shares == {first: 1_000, second: 3_000}


def test_the_total_stays_within_the_budget_when_no_minimum_applies() -> None:
    sources = {new_id(): 50_000 + i * 1_000 for i in range(4)}

    shares = allocate_tokens(sources, budget=60_000)

    assert sum(shares.values()) <= 60_000
    assert set(shares) == set(sources)


def test_a_custom_minimum_is_used() -> None:
    big, small = new_id(), new_id()

    shares = allocate_tokens({big: 100_000, small: 5_000}, budget=10_000, minimum=4_000)

    assert shares[small] == 4_000


def test_sources_of_no_size_get_nothing() -> None:
    first, second = new_id(), new_id()

    assert allocate_tokens({first: 0, second: 0}, budget=1_000) == {first: 0, second: 0}


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.integers(min_value=0, max_value=300_000), min_size=1, max_size=8),
    st.integers(min_value=0, max_value=500_000),
)
def test_property_allocation_respects_size_minimum_and_budget(
    sizes: list[int], budget: int
) -> None:
    sources = {new_id(): size for size in sizes}

    shares = allocate_tokens(sources, budget)

    for source_id, size in sources.items():
        assert min(2_000, size) <= shares[source_id] <= size
    assert sum(shares.values()) <= budget + sum(min(2_000, size) for size in sizes)


# - - - evenly spaced sampling - - -


def run(token_counts: list[int]) -> tuple[list[Passage], Source]:
    source = make_source()
    return [
        make_passage(source.id, seq, f"text {seq}", tokens=tokens)
        for seq, tokens in enumerate(token_counts, start=1)
    ], source


def test_everything_is_returned_when_it_fits_the_budget() -> None:
    passages, _ = run([10] * 5)

    assert evenly_spaced(passages, 50) == passages


def test_the_sample_starts_with_the_first_passage() -> None:
    passages, _ = run([10] * 30)

    assert evenly_spaced(passages, 70)[0] is passages[0]


def test_the_sample_is_evenly_spaced_and_within_the_budget() -> None:
    passages, _ = run([10] * 10)

    sample = evenly_spaced(passages, 50)

    assert seqs(sample) == [1, 3, 5, 7, 9]


def test_the_sample_keeps_document_order() -> None:
    passages, _ = run([10] * 40)

    assert seqs(evenly_spaced(passages, 120)) == sorted(
        seqs(evenly_spaced(passages, 120))
    )


def test_a_budget_for_one_passage_returns_the_first() -> None:
    passages, _ = run([10] * 8)

    assert evenly_spaced(passages, 15) == [passages[0]]


def test_the_sample_shrinks_until_uneven_passages_fit() -> None:
    passages, _ = run([50, 50, 1, 1, 50, 50])

    sample = evenly_spaced(passages, 150)

    assert seqs(sample) == [1, 3, 5]


def test_when_the_first_passage_is_too_big_the_first_that_fits_is_used() -> None:
    passages, _ = run([1000, 10, 10])

    assert evenly_spaced(passages, 50) == [passages[1]]


def test_nothing_is_returned_when_no_passage_fits() -> None:
    passages, _ = run([100, 200])

    assert evenly_spaced(passages, 50) == []


def test_nothing_is_returned_for_no_passages_or_no_budget() -> None:
    passages, _ = run([10, 10])

    assert evenly_spaced([], 100) == []
    assert evenly_spaced(passages, 0) == []


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.integers(min_value=1, max_value=600), min_size=1, max_size=120),
    st.integers(min_value=0, max_value=5000),
)
def test_property_a_sample_is_ordered_within_budget_and_not_empty_if_one_fits(
    token_counts: list[int], budget: int
) -> None:
    passages, _ = run(token_counts)

    sample = evenly_spaced(passages, budget)

    assert sum(p.token_estimate for p in sample) <= budget
    assert seqs(sample) == sorted(set(seqs(sample)))
    if any(t <= budget for t in token_counts):
        assert sample
    if token_counts[0] <= budget:
        assert sample[0] is passages[0]


# - - - stratified sample of a large notebook - - -


def test_a_large_notebook_is_sampled_in_proportion_to_source_size() -> None:
    large, medium = make_source("Large"), make_source("Medium")
    by_source = {
        large.id: passages_of(large, 300, tokens=100),
        medium.id: passages_of(medium, 100, tokens=100),
    }
    sizes = {s: sum(p.token_estimate for p in ps) for s, ps in by_source.items()}
    assert choose_studio_mode(sum(sizes.values()), 20_000) == "sample"

    budget = allocate_tokens(sizes, 20_000)
    chosen = {s: evenly_spaced(by_source[s], budget[s]) for s in by_source}
    pack = build_pack([large, medium], chosen, "sample")

    assert pack.sampled is True
    assert len(chosen[large.id]) == 150
    assert len(chosen[medium.id]) == 50
    assert pack.token_estimate == 20_000
    assert [p.seq for p in pack.sources[0].passages][:3] == [1, 3, 5]


def test_a_tiny_source_in_a_large_notebook_still_gets_its_minimum() -> None:
    large, tiny = make_source("Large"), make_source("Tiny")
    by_source = {
        large.id: passages_of(large, 1000, tokens=100),
        tiny.id: passages_of(tiny, 30, tokens=100),
    }
    sizes = {s: sum(p.token_estimate for p in ps) for s, ps in by_source.items()}

    budget = allocate_tokens(sizes, 10_000)
    chosen = evenly_spaced(by_source[tiny.id], budget[tiny.id])

    assert budget[tiny.id] == 2_000
    assert len(chosen) == 20


def test_pack_token_estimate_matches_the_estimate_of_the_text() -> None:
    source = make_source()
    passage = make_passage(source.id, 1, "x" * 280)

    pack = build_pack([source], {source.id: [passage]}, "full")

    assert pack.token_estimate == estimate_tokens(280) == 100


def test_small_sources_go_to_the_studio_whole() -> None:
    """Three short course steps (the Derivatives 101 case) are sent in full."""
    steps = [
        make_source("What is a derivative", position=0),
        make_source("Check yourself", position=1),
        make_source("Flash cards", position=2),
    ]
    texts = [
        "# What is a derivative?\n\nThe derivative measures how fast it changes.",
        "Test: 2 questions.\n\nQuestion 1 (single choice): Derivative of x^2?",
        "Flash cards: 1 card.\n\nCard 1\nFront: (c)'\nBack: 0",
    ]
    by_source = {s.id: [make_passage(s.id, 1, text)] for s, text in zip(steps, texts)}
    total = sum(p.token_estimate for ps in by_source.values() for p in ps)

    assert choose_studio_mode(total, 150_000) == "full"
    pack = build_pack(steps, by_source, "full")
    assert [s.title for s in pack.sources] == [s.title for s in steps]
    assert [p.text for s in pack.sources for p in s.passages] == texts
    assert set(pack.labels) == {"S1:P1", "S2:P1", "S3:P1"}
