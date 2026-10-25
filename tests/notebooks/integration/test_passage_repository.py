"""NB-5, NB-14: passages in PostgreSQL (replace, read, neighbours, lexical search)."""

import random
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    DraftPassage,
    Notebook,
    Passage,
    SourceGuide,
)
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    drafts_from_texts,
    make_notebook,
    make_source,
)

import pytest
from sqlalchemy.exc import IntegrityError

PHOTOSYNTHESIS_RU = "В фотосинтезе растения используют энергию света и воду."
PHOTOSYNTHESIS_RU_2 = "Как происходит фотосинтез: хлорофилл поглощает свет в листьях."
CELL_RU = "Митохондрии вырабатывают энергию для клетки."
PHOTOSYNTHESIS_UZ = "Fotosintez jarayonida o'simliklar quyosh nurini qabul qiladi."
PHOTOSYNTHESIS_UZ_ENDING = "Fotosintezda barglardagi xlorofill yorug'likni yutadi."
CELL_UZ = "Mitoxondriya hujayraning energiya stansiyasi hisoblanadi."


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


async def _search(
    uow_factory: UowFactory,
    notebook: Notebook,
    source_ids: list[UUID],
    query: str,
    limit: int = 10,
) -> list[Passage]:
    async with uow_factory() as uow:
        return await uow.passages.search(notebook.id, source_ids, query, limit)


def _texts(found: list[Passage]) -> list[str]:
    return [p.text for p in found]


# - - - storage (documents) - - -


async def test_create_stores_a_document_and_sources_read_its_passages(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-5: passages belong to a document; a source reads them with its own ids."""
    drafts = [
        DraftPassage(
            seq=1,
            text="First passage.",
            char_start=0,
            char_end=14,
            token_estimate=5,
            page=3,
            heading="Intro",
        ),
        DraftPassage(
            seq=2, text="Second.", char_start=16, char_end=23, token_estimate=3
        ),
    ]
    async with uow_factory() as uow:
        document = await uow.documents.create(
            "a" * 64, drafts, word_count=3, char_count=23, token_estimate=8
        )
        await uow.commit()
    source = await make_source(uow_factory, notebook, texts=(), document_id=document.id)

    async with uow_factory() as uow:
        loaded = await uow.passages.list_for_source(source.id, after_seq=0, limit=10)

    assert document.passage_count == 2 and document.content_hash == "a" * 64
    assert [(p.seq, p.page, p.heading) for p in loaded] == [
        (1, 3, "Intro"),
        (2, None, None),
    ]
    assert {p.source_id for p in loaded} == {source.id}
    assert {p.notebook_id for p in loaded} == {notebook.id}
    assert [p.id.version for p in loaded] == [7, 7]


async def test_passages_carry_the_hash_of_their_text(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: an embedding attaches to a passage by the hash of its text."""
    first = await make_source(uow_factory, notebook, texts=("Alpha beta.", "Gamma."))
    second = await make_source(uow_factory, notebook, texts=("Gamma.", "Delta."))

    async with uow_factory() as uow:
        a = await uow.passages.list_for_source(first.id, after_seq=0, limit=10)
        b = await uow.passages.list_for_source(second.id, after_seq=0, limit=10)
        hit = await uow.passages.search(notebook.id, [first.id], "alpha", 5)

    assert first.document_id != second.document_id
    assert [p.content_hash for p in a] == [passage_hash(p.text) for p in a]
    assert a[1].content_hash == b[0].content_hash  # the same text, two documents
    assert a[1].id != b[0].id
    assert [p.content_hash for p in hit] == [passage_hash("Alpha beta.")]


async def test_sources_with_the_same_text_share_the_passages(
    uow_factory: UowFactory, notebook: Notebook, other_student: Actor
) -> None:
    """NB-5: a text is stored once; each notebook reads the same passage ids."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    mine = await make_source(uow_factory, notebook, texts=("shared one", "shared two"))
    other = await make_source(uow_factory, theirs, texts=("shared one", "shared two"))

    async with uow_factory() as uow:
        a = await uow.passages.list_for_source(mine.id, after_seq=0, limit=10)
        b = await uow.passages.list_for_source(other.id, after_seq=0, limit=10)

    assert mine.document_id == other.document_id is not None
    assert [p.id for p in a] == [p.id for p in b]
    assert {p.notebook_id for p in a} == {notebook.id}
    assert {p.notebook_id for p in b} == {theirs.id}


async def test_create_returns_the_document_that_exists_for_the_hash(
    uow_factory: UowFactory,
) -> None:
    """NB-5: storing the same normalized text twice keeps one document."""
    drafts = drafts_from_texts(("one", "two"))
    async with uow_factory() as uow:
        first = await uow.documents.create(
            "b" * 64, drafts, word_count=2, char_count=8, token_estimate=2
        )
        again = await uow.documents.create(
            "b" * 64, drafts, word_count=2, char_count=8, token_estimate=2
        )
        found = await uow.documents.find_by_hash("b" * 64)

    assert again == first == found


async def test_seq_is_unique_within_a_document(uow_factory: UowFactory) -> None:
    """NB-5: two passages of one document cannot share a number."""
    drafts = drafts_from_texts(("one", "two"))
    clash = [drafts[0], replace(drafts[1], seq=1)]

    async with uow_factory() as uow:
        with pytest.raises(IntegrityError):
            await uow.documents.create(
                "c" * 64, clash, word_count=2, char_count=6, token_estimate=2
            )


async def test_aliases_find_the_document_of_a_file_and_the_first_one_wins(
    uow_factory: UowFactory,
) -> None:
    """NB-5: a file id names its text, so a second reader skips the reading."""
    async with uow_factory() as uow:
        one = await uow.documents.create(
            "d" * 64, [], word_count=0, char_count=0, token_estimate=0
        )
        two = await uow.documents.create(
            "e" * 64, [], word_count=0, char_count=0, token_estimate=0
        )
        await uow.documents.add_aliases(["file:1", "file:2"], one.id)
        await uow.documents.add_aliases(["file:1"], two.id)
        found = await uow.documents.find_by_alias("file:1")
        missing = await uow.documents.find_by_alias("file:3")

    assert found == one and missing is None


async def test_guides_are_kept_per_document_and_language(
    uow_factory: UowFactory,
) -> None:
    """NB-6: a guide is written once per language; the first one is kept."""
    first = SourceGuide(summary="First.", key_topics=["a"], questions=["q?"])
    second = SourceGuide(summary="Second.", key_topics=["b"], questions=["r?"])
    async with uow_factory() as uow:
        document = await uow.documents.create(
            "f" * 64, [], word_count=0, char_count=0, token_estimate=0
        )
        await uow.documents.save_guide(document.id, "en", first)
        await uow.documents.save_guide(document.id, "en", second)
        await uow.documents.save_guide(document.id, "ru", second)
        en = await uow.documents.get_guide(document.id, "en")
        ru = await uow.documents.get_guide(document.id, "ru")
        uz = await uow.documents.get_guide(document.id, "uz")

    assert (en, ru, uz) == (first, second, None)


async def test_delete_unused_keeps_documents_a_source_points_at(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-3: the purge removes only old documents that no source holds."""
    used = await make_source(uow_factory, notebook, texts=("kept text",))
    async with uow_factory() as uow:
        orphan = await uow.documents.create(
            "9" * 64,
            drafts_from_texts(("orphan",)),
            word_count=1,
            char_count=6,
            token_estimate=2,
        )
        await uow.commit()
    future = datetime.now(UTC) + timedelta(days=1)

    async with uow_factory() as uow:
        too_new = await uow.documents.delete_unused(
            datetime.now(UTC) - timedelta(days=1), 10
        )
        removed = await uow.documents.delete_unused(future, 10)
        gone = await uow.documents.find_by_hash(orphan.content_hash)
        kept = await uow.documents.find_by_hash(used.content_hash or "")

    assert too_new == 0 and removed == 1
    assert gone is None and kept is not None


async def test_get_and_get_many_return_what_the_notebook_holds(
    uow_factory: UowFactory, notebook: Notebook, other_student: Actor
) -> None:
    """NB-5: single and bulk reads skip unknown ids and other notebooks' passages."""
    source = await make_source(uow_factory, notebook, texts=("a", "b", "c"))
    stranger = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, stranger, texts=("only theirs",))
    async with uow_factory() as uow:
        stored = await uow.passages.list_for_source(source.id, after_seq=0, limit=10)

    async with uow_factory() as uow:
        one = await uow.passages.get(stored[1].id, notebook.id)
        missing = await uow.passages.get(new_id(), notebook.id)
        elsewhere = await uow.passages.get(stored[1].id, stranger.id)
        many = await uow.passages.get_many(
            [stored[2].id, new_id(), stored[0].id], notebook.id
        )
        none = await uow.passages.get_many([], notebook.id)

    assert one == stored[1] and missing is None and elsewhere is None
    assert sorted(many, key=lambda p: p.seq) == [stored[0], stored[2]]
    assert none == []


async def test_list_for_source_pages_by_seq(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-5: the source viewer reads passages after a number, ascending."""
    source = await make_source(
        uow_factory, notebook, texts=tuple(f"passage {n}" for n in range(1, 8))
    )

    async with uow_factory() as uow:
        first = await uow.passages.list_for_source(source.id, after_seq=0, limit=3)
        second = await uow.passages.list_for_source(
            source.id, after_seq=first[-1].seq, limit=3
        )
        last = await uow.passages.list_for_source(source.id, after_seq=6, limit=3)
        past_end = await uow.passages.list_for_source(source.id, after_seq=7, limit=3)

    assert [p.seq for p in first] == [1, 2, 3]
    assert [p.seq for p in second] == [4, 5, 6]
    assert [p.seq for p in last] == [7]
    assert past_end == []


async def test_list_for_sources_follows_the_given_source_order(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: full context lists sources in the requested order, passages by seq."""
    a = await make_source(uow_factory, notebook, texts=("a1", "a2"))
    b = await make_source(uow_factory, notebook, texts=("b1", "b2"))
    c = await make_source(uow_factory, notebook, texts=("c1",))

    async with uow_factory() as uow:
        ordered = await uow.passages.list_for_sources([c.id, a.id, b.id])
        subset = await uow.passages.list_for_sources([b.id])
        empty = await uow.passages.list_for_sources([])

    assert _texts(ordered) == ["c1", "a1", "a2", "b1", "b2"]
    assert _texts(subset) == ["b1", "b2"]
    assert empty == []


async def test_neighbours_returns_the_surrounding_passages_in_order(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-5: the viewer shows `context` passages on each side, cut at the ends."""
    source = await make_source(
        uow_factory, notebook, texts=tuple(f"p{n}" for n in range(1, 8))
    )

    async with uow_factory() as uow:
        middle = await uow.passages.neighbours(source.id, 4, 2)
        start = await uow.passages.neighbours(source.id, 1, 2)
        end = await uow.passages.neighbours(source.id, 7, 3)
        none = await uow.passages.neighbours(source.id, 4, 0)

    assert (_texts(middle[0]), _texts(middle[1])) == (["p2", "p3"], ["p5", "p6"])
    assert (_texts(start[0]), _texts(start[1])) == ([], ["p2", "p3"])
    assert (_texts(end[0]), _texts(end[1])) == (["p4", "p5", "p6"], [])
    assert none == ([], [])


# - - - lexical search - - -


async def test_russian_question_finds_the_passage_with_another_word_form(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: "как происходит фотосинтез" finds "фотосинтезе", not unrelated text."""
    source = await make_source(
        uow_factory, notebook, texts=(CELL_RU, PHOTOSYNTHESIS_RU, CELL_RU + " Ещё.")
    )

    found = await _search(
        uow_factory, notebook, [source.id], "как происходит фотосинтез"
    )

    assert _texts(found) == [PHOTOSYNTHESIS_RU]


async def test_passage_with_more_of_the_question_ranks_first(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: the passage that matches both words beats the one that matches one."""
    source = await make_source(
        uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU, PHOTOSYNTHESIS_RU_2)
    )

    found = await _search(
        uow_factory, notebook, [source.id], "как происходит фотосинтез в листьях"
    )

    assert _texts(found) == [PHOTOSYNTHESIS_RU_2, PHOTOSYNTHESIS_RU]


async def test_uzbek_word_endings_match_in_both_directions(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: "fotosintezda" finds "fotosintez" and the other way round."""
    source = await make_source(
        uow_factory,
        notebook,
        texts=(CELL_UZ, PHOTOSYNTHESIS_UZ, PHOTOSYNTHESIS_UZ_ENDING),
    )

    with_ending = await _search(uow_factory, notebook, [source.id], "fotosintezda")
    with_stem = await _search(uow_factory, notebook, [source.id], "fotosintez")
    plural = await _search(uow_factory, notebook, [source.id], "fotosintezlarning")

    expected = {PHOTOSYNTHESIS_UZ, PHOTOSYNTHESIS_UZ_ENDING}
    assert set(_texts(with_ending)) == expected
    assert set(_texts(with_stem)) == expected
    assert set(_texts(plural)) == expected


@pytest.mark.parametrize(
    "query", ["o'simliklar", "oʻsimliklar", "o’simliklar", "OʼSIMLIKLAR"]
)
async def test_uzbek_apostrophes_match_whatever_spelling_the_text_uses(
    uow_factory: UowFactory, notebook: Notebook, query: str
) -> None:
    """NB-14: oʻ gʻ are found with ' ’ ʻ ʼ in the query and in the text."""
    texts = (
        "O'simliklar quyoshdan energiya oladi.",
        "Oʻsimliklar suv bilan oziqlanadi.",
        "O’simliklar havodan karbonat angidrid oladi.",
        "Oʼsimliklar ildiz orqali suv shimadi.",
        CELL_UZ,
    )
    source = await make_source(uow_factory, notebook, texts=texts)

    found = await _search(uow_factory, notebook, [source.id], query)

    assert set(_texts(found)) == set(texts[:4])


async def test_only_the_given_sources_of_the_given_notebook_are_searched(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-14: unselected sources and other notebooks never appear in the result."""
    selected = await make_source(uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU,))
    not_selected = await make_source(
        uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU_2,)
    )
    elsewhere = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, elsewhere, texts=("Фотосинтез в другом блокноте.",))

    only_selected = await _search(uow_factory, notebook, [selected.id], "фотосинтез")
    both = await _search(
        uow_factory, notebook, [selected.id, not_selected.id], "фотосинтез"
    )
    wrong_notebook = await _search(
        uow_factory, elsewhere, [selected.id, not_selected.id], "фотосинтез"
    )

    assert _texts(only_selected) == [PHOTOSYNTHESIS_RU]
    assert set(_texts(both)) == {PHOTOSYNTHESIS_RU, PHOTOSYNTHESIS_RU_2}
    assert wrong_notebook == []


async def test_limit_is_honoured_and_ties_go_by_source_then_seq(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: equally good passages come in reading order; `limit` cuts the list."""
    first = await make_source(
        uow_factory, notebook, texts=("Фотосинтез раз.", "Фотосинтез два.")
    )
    second = await make_source(uow_factory, notebook, texts=("Фотосинтез три.",))
    ids = [first.id, second.id]

    found = await _search(uow_factory, notebook, ids, "фотосинтез", limit=10)
    two = await _search(uow_factory, notebook, ids, "фотосинтез", limit=2)
    zero = await _search(uow_factory, notebook, ids, "фотосинтез", limit=0)

    assert [(p.source_id, p.seq) for p in found] == sorted(
        (p.source_id, p.seq) for p in found
    )
    assert len(found) == 3
    assert two == found[:2]
    assert zero == []


@pytest.mark.parametrize(
    "query",
    ["", "   ", "как это", "что за", "a b c", "и в на", "the and for", "?!...", "ab"],
)
async def test_a_question_without_content_words_finds_nothing(
    uow_factory: UowFactory, notebook: Notebook, query: str
) -> None:
    """NB-14: empty, stop-word-only and too-short queries return an empty list."""
    source = await make_source(uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU,))

    assert await _search(uow_factory, notebook, [source.id], query) == []


async def test_search_without_sources_finds_nothing(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: no selected source, no result."""
    await make_source(uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU,))

    assert await _search(uow_factory, notebook, [], "фотосинтез") == []


async def test_query_syntax_characters_are_harmless(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: tsquery operators and quotes in a question never break the search."""
    source = await make_source(uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU,))

    found = await _search(
        uow_factory,
        notebook,
        [source.id],
        "фотосинтез & | ! (энергия) :* <-> \\ ' \" ); DROP TABLE x; --",
    )

    assert _texts(found) == [PHOTOSYNTHESIS_RU]


async def test_a_long_question_is_cut_to_twelve_words(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: a long question is cut to 12 distinct content words."""
    source = await make_source(
        uow_factory, notebook, texts=(PHOTOSYNTHESIS_RU, CELL_RU)
    )
    filler = " ".join(f"слово{n}" for n in range(12))

    found = await _search(
        uow_factory, notebook, [source.id], f"{filler} фотосинтез фотосинтез"
    )

    assert found == []  # "фотосинтез" is the 13th word and is not read


# - - - speed - - -

SYLLABLES = [
    "ka",
    "ri",
    "tu",
    "mo",
    "be",
    "sha",
    "lin",
    "dor",
    "ven",
    "ush",
    "qo",
    "ra",
]


def _vocabulary(rng: random.Random, size: int) -> list[str]:
    return [
        "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4)))
        for _ in range(size)
    ]


@pytest.mark.slow
async def test_search_in_a_notebook_of_five_thousand_passages_takes_under_150_ms(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: ranking on the fly stays within the budget of a chat turn."""
    rng = random.Random(7)
    vocabulary = _vocabulary(rng, 3000)
    planted = ["фотосинтез", "листьях", "fotosintezda", "quyosh"]
    source_ids: list[UUID] = []
    for _ in range(10):
        texts = []
        for _ in range(500):
            words = [rng.choice(vocabulary) for _ in range(100)]
            if rng.random() < 0.03:
                words[rng.randrange(100)] = rng.choice(planted)
            texts.append(" ".join(words))
        async with uow_factory() as uow:
            document = await uow.documents.create(
                new_id().hex + new_id().hex[:32],
                drafts_from_texts(tuple(texts)),
                word_count=1,
                char_count=1,
                token_estimate=1,
            )
            await uow.commit()
        source = await make_source(
            uow_factory, notebook, texts=(), document_id=document.id
        )
        source_ids.append(source.id)
    question = "как происходит фотосинтез в листьях растений, fotosintezda quyosh"

    timings = []
    for _ in range(5):
        started = time.perf_counter()
        found = await _search(uow_factory, notebook, source_ids, question, limit=24)
        timings.append((time.perf_counter() - started) * 1000)

    assert len(found) == 24
    assert min(timings) < 150, timings
