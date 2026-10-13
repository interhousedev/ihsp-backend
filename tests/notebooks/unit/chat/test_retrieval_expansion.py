"""NB-6, NB-14: multi-hop retrieval and query decomposition with a small model."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.multi_hop_retrieval import MultiHopRetrieval
from app.modules.notebooks.application.query_decomposer import QueryDecomposer
from app.modules.notebooks.application.retrieval_expander import RetrievalExpander
from app.modules.notebooks.domain.entities import Passage
from app.modules.notebooks.domain.retrieval_plan import (
    DECOMPOSE_SCHEMA_NAME,
    SUFFICIENCY_SCHEMA_NAME,
    clean_queries,
    interleave,
    looks_complex,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from tests.fakes.notebooks.llm import ScriptedLlm

import pytest

SOURCE = uuid4()
NOTEBOOK = uuid4()
COMPLEX = "Compare photosynthesis and respiration: where does each happen and why?"


def passage(text: str, seq: int = 0) -> Passage:
    """A stored passage of the one source."""
    return Passage(
        id=uuid4(),
        source_id=SOURCE,
        notebook_id=NOTEBOOK,
        seq=seq,
        text=text,
        char_start=0,
        char_end=len(text),
        token_estimate=10,
    )


class Corpus:
    """A search over a fixed map of query -> passages that records the queries."""

    def __init__(self, answers: dict[str, list[Passage]]) -> None:
        """Keep the answers."""
        self.answers = answers
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[Passage]:
        """The passages of the query, at most `limit`."""
        self.queries.append(query)
        return self.answers.get(query, [])[:limit]


def configured(settings: Settings, **notebooks: object) -> Settings:
    """Settings with notebook overrides."""
    return settings.model_copy(
        update={"notebooks": settings.notebooks.model_copy(update=notebooks)}
    )


def multi_hop(
    settings: Settings, gateway: ScriptedLlm, **over: object
) -> MultiHopRetrieval:
    """Multi-hop retrieval switched on (plus overrides) over a scripted gateway."""
    tuned = configured(settings, multi_hop_enabled=True, **over)
    return MultiHopRetrieval(NotebookLlm(gateway, tuned), tuned)


def decomposer(
    settings: Settings, gateway: ScriptedLlm, **over: object
) -> QueryDecomposer:
    """Query decomposition switched on (plus overrides) over a scripted gateway."""
    tuned = configured(settings, decompose_enabled=True, **over)
    return QueryDecomposer(NotebookLlm(gateway, tuned), tuned)


def ids(passages: Sequence[Passage]) -> list[UUID]:
    """The ids in order."""
    return [p.id for p in passages]


# - - - Domain rules - - -


def test_short_or_single_questions_are_not_complex() -> None:
    """The heuristic keeps the classification call off plain questions."""
    assert not looks_complex("What is a cell?")
    assert not looks_complex("Explain the structure of the plant cell wall to me")


def test_joined_long_or_multi_question_texts_are_complex() -> None:
    """Joiners in en/ru/uz, two question marks or a long text."""
    assert looks_complex(COMPLEX)
    assert looks_complex("Сравни митоз и мейоз по числу делений и результату")
    assert looks_complex("What is mitosis? What is meiosis? Explain both stages.")
    assert looks_complex("x" * 200)


def test_queries_are_trimmed_distinct_unseen_and_limited() -> None:
    """Junk, repeats and already asked queries are dropped."""
    raw = ["  a   b ", "A B", "", None, "seen", "c", "d"]

    assert clean_queries(raw, 2, seen=["seen"]) == ["a b", "c"]
    assert clean_queries("not a list", 3) == []


def test_interleave_takes_the_best_of_each_group_first_without_repeats() -> None:
    """Round-robin keeps every sub-question represented under a small limit."""
    a1, a2, b1 = passage("a1"), passage("a2"), passage("b1")

    assert ids(interleave([[a1, a2], [b1, a1]], 3)) == ids([a1, b1, a2])


# - - - Multi-hop - - -


async def test_sufficient_passages_need_no_second_search(settings: Settings) -> None:
    """One cheap call says yes: the hits stay as they are."""
    gateway = ScriptedLlm()
    gateway.queue_json({"sufficient": True, "queries": []})
    first = [passage("Leaves make sugar.")]
    corpus = Corpus({})

    hits = await multi_hop(settings, gateway).expand("Q?", first, corpus.search)

    assert hits == first
    assert corpus.queries == []
    request = gateway.json_requests[0]
    assert request["schema_name"] == SUFFICIENCY_SCHEMA_NAME
    assert request["tuning"].task == AiTask.RETRIEVAL_PLAN.value


async def test_gaps_are_searched_again_and_new_passages_appended_once(
    settings: Settings,
) -> None:
    """Follow-up queries add only passages not found before."""
    known = passage("Photosynthesis happens in chloroplasts.")
    extra = passage("Respiration happens in mitochondria.")
    gateway = ScriptedLlm()
    gateway.queue_json({"sufficient": False, "queries": ["respiration place"]})
    gateway.queue_json({"sufficient": True, "queries": []})
    corpus = Corpus({"respiration place": [known, extra]})

    hits = await multi_hop(settings, gateway).expand(COMPLEX, [known], corpus.search)

    assert ids(hits) == ids([known, extra])
    assert corpus.queries == ["respiration place"]


async def test_hops_stop_early_when_follow_ups_find_nothing_new(
    settings: Settings,
) -> None:
    """No new passage after a hop: no further cheap call."""
    known = passage("A")
    gateway = ScriptedLlm()
    gateway.queue_json({"sufficient": False, "queries": ["q1"]})
    corpus = Corpus({"q1": [known]})

    hits = await multi_hop(settings, gateway, multi_hop_max_hops=3).expand(
        "Q?", [known], corpus.search
    )

    assert hits == [known]
    assert gateway.calls == 1


async def test_hops_and_queries_per_hop_are_bounded(settings: Settings) -> None:
    """At most `max_hops` cheap calls and `queries_per_hop` searches each."""
    gateway = ScriptedLlm()
    for hop in range(3):
        gateway.queue_json(
            {"sufficient": False, "queries": [f"h{hop}a", f"h{hop}b", f"h{hop}c"]}
        )
    answers = {f"h{h}{s}": [passage(f"{h}{s}")] for h in range(3) for s in "abc"}
    corpus = Corpus(answers)

    hits = await multi_hop(
        settings, gateway, multi_hop_max_hops=2, multi_hop_queries_per_hop=2
    ).expand("Q?", [passage("first")], corpus.search)

    assert gateway.calls == 2
    assert corpus.queries == ["h0a", "h0b", "h1a", "h1b"]
    assert len(hits) == 5


@pytest.mark.parametrize(
    "error",
    [
        AiProviderError(support_details="HTTP 503"),
        AiInvalidOutputError(support_details="bad"),
    ],
)
async def test_a_failing_small_model_keeps_the_first_hits(
    settings: Settings, error: Exception
) -> None:
    """The chat never fails because the planner did."""
    gateway = ScriptedLlm()
    gateway.queue_error(error)
    first = [passage("A")]

    hits = await multi_hop(settings, gateway).expand("Q?", first, Corpus({}).search)

    assert hits == first


async def test_switched_off_multi_hop_makes_no_call(settings: Settings) -> None:
    """The default keeps retrieval single-shot."""
    gateway = ScriptedLlm()
    retrieval = MultiHopRetrieval(NotebookLlm(gateway, settings), settings)
    first = [passage("A")]

    hits = await retrieval.expand("Q?", first, Corpus({}).search)

    assert hits == first
    assert gateway.calls == 0


# - - - Decomposition - - -


async def test_a_simple_question_is_not_sent_to_the_classifier(
    settings: Settings,
) -> None:
    """The heuristic saves the cheap call."""
    gateway = ScriptedLlm()

    parts = await decomposer(settings, gateway).parts("What is a cell?")

    assert parts == []
    assert gateway.calls == 0


async def test_a_complex_question_is_split_into_bounded_parts(
    settings: Settings,
) -> None:
    """The classifier's parts, at most `decompose_max_parts`."""
    gateway = ScriptedLlm()
    gateway.queue_json({"complex": True, "parts": ["p1", "p2", "p3"]})

    parts = await decomposer(settings, gateway, decompose_max_parts=2).parts(COMPLEX)

    assert parts == ["p1", "p2"]
    request = gateway.json_requests[0]
    assert request["schema_name"] == DECOMPOSE_SCHEMA_NAME
    assert request["tuning"].task == AiTask.QUERY_DECOMPOSE.value


async def test_a_question_the_classifier_calls_simple_is_kept_whole(
    settings: Settings,
) -> None:
    """`complex: false` (or a single part) means no split."""
    gateway = ScriptedLlm()
    gateway.queue_json({"complex": True, "parts": ["only one"]})

    assert await decomposer(settings, gateway).parts(COMPLEX) == []


async def test_each_part_is_retrieved_and_the_results_interleaved(
    settings: Settings,
) -> None:
    """A focused pack: the best passages of every sub-question within the limit."""
    gateway = ScriptedLlm()
    gateway.queue_json({"complex": True, "parts": ["photo", "resp"]})
    photo = [passage("p1"), passage("p2"), passage("p3")]
    resp = [passage("r1"), passage("r2")]
    corpus = Corpus({"photo": photo, "resp": resp})

    hits = await decomposer(settings, gateway).retrieve(COMPLEX, corpus.search, 3)

    assert hits is not None
    assert ids(hits) == ids([photo[0], resp[0], photo[1]])
    assert corpus.queries == ["photo", "resp"]


async def test_a_failing_classifier_means_no_decomposition(
    settings: Settings,
) -> None:
    """Provider errors fall back to the whole question."""
    gateway = ScriptedLlm()
    gateway.queue_error(AiProviderError(support_details="HTTP 503"))

    assert (
        await decomposer(settings, gateway).retrieve(COMPLEX, Corpus({}).search, 5)
        is None
    )


# - - - Both together - - -


async def test_the_expander_searches_the_question_when_nothing_is_on(
    settings: Settings,
) -> None:
    """Defaults: one plain search, no model call."""
    gateway = ScriptedLlm()
    llm = NotebookLlm(gateway, settings)
    expander = RetrievalExpander(
        QueryDecomposer(llm, settings), MultiHopRetrieval(llm, settings)
    )
    found = [passage("A")]
    corpus = Corpus({"Q?": found})

    hits = await expander.hits("Q?", corpus.search, 24)

    assert hits == found
    assert gateway.calls == 0


async def test_the_expander_decomposes_then_fills_gaps(settings: Settings) -> None:
    """Sub-question retrieval first, then one multi-hop round."""
    tuned = configured(settings, decompose_enabled=True, multi_hop_enabled=True)
    gateway = ScriptedLlm()
    gateway.queue_json({"complex": True, "parts": ["photo", "resp"]})
    gateway.queue_json({"sufficient": False, "queries": ["why"]})
    gateway.queue_json({"sufficient": True, "queries": []})
    p, r, w = passage("p"), passage("r"), passage("w")
    corpus = Corpus({"photo": [p], "resp": [r], "why": [w]})
    llm = NotebookLlm(gateway, tuned)
    expander = RetrievalExpander(
        QueryDecomposer(llm, tuned), MultiHopRetrieval(llm, tuned)
    )

    hits = await expander.hits(COMPLEX, corpus.search, 24)

    assert ids(hits) == ids([p, r, w])
    assert corpus.queries == ["photo", "resp", "why"]
