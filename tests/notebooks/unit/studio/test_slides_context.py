"""NB-8, NB-11: what a slide deck sees of realistic, multi-language sources (§ 3.3.2).

The samples go through the real extractors (PDF, DOCX, TXT in UTF-8 and in
Windows-1251) and the chunker, then through `ContextBuilder.for_studio` over an
in-memory passage store. Every selected source must reach the prompt, in order and
complete when it fits; a large notebook is sampled fairly and the student's focus
never pushes the context over the cap.
"""

from typing import cast
from uuid import UUID

from app.modules.notebooks.application.context_builder import ContextBuilder
from app.modules.notebooks.domain.chunker import chunk_source
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.entities import Passage, Source
from app.modules.notebooks.domain.sources_block import render_sources_block
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.settings import Settings
from app.shared.ids import new_id
from tests.notebooks.fixtures.slides import (
    PAGE_BREAK,
    SAMPLES,
    MemoryPassages,
    MemoryUow,
    chunked,
    source_text,
    stored,
)

import pytest

ALL = ["industrial_revolution", "factory_acts", "peter_reforms", "peter_dates"]
ALL += ["amir_temur"]
NOTEBOOK = new_id()


async def studio_pack(
    sources: list[Source],
    passages: dict[UUID, list[Passage]],
    settings: Settings,
    *,
    cap: int,
    prompt: str | None = None,
) -> ContextPack:
    uow = cast(NotebooksUnitOfWork, MemoryUow(MemoryPassages(passages)))
    return await ContextBuilder(settings).for_studio(
        uow, NOTEBOOK, sources, prompt=prompt, cap_tokens=cap
    )


def squeezed(text: str) -> str:
    """Text without any whitespace, to compare passages with the whole source."""
    return "".join(text.split())


def long_pdf_key_text() -> str:
    """Five copies of the eight PDF pages (a 40-page book), each copy marked."""
    pages = source_text("industrial_revolution").split(PAGE_BREAK)
    return PAGE_BREAK.join(
        f"Part {part}. {page.strip()}" for part in range(1, 6) for page in pages
    )


def with_long_pdf(
    keys: list[str],
) -> tuple[list[Source], dict[UUID, list[Passage]]]:
    """The samples, with the PDF replaced by a 40-page version of it."""
    sources, passages = stored(keys, NOTEBOOK)
    text = long_pdf_key_text()
    starts, offset = [], 0
    for page in text.split(PAGE_BREAK):
        starts.append(offset)
        offset += len(page) + len(PAGE_BREAK)
    result = chunk_source(text, page_starts=starts)
    pdf = sources[0]
    pdf.token_estimate = result.token_estimate
    passages[pdf.id] = [
        Passage(
            id=new_id(),
            source_id=pdf.id,
            notebook_id=NOTEBOOK,
            seq=d.seq,
            text=d.text,
            char_start=d.char_start,
            char_end=d.char_end,
            token_estimate=d.token_estimate,
            page=d.page,
            heading=d.heading,
        )
        for d in result.passages
    ]
    return sources, passages


# - - - Extraction and chunking - - -


def test_every_sample_is_read_completely_by_the_real_extractors() -> None:
    """NB-2: PDF pages, DOCX headings and lists, cp1251 and Uzbek text all arrive."""
    for key, expected in {
        "industrial_revolution": ["Cromford Mill", "Rainhill Trials", "fossil fuels"],
        "factory_acts": ["four factory inspectors", "Ten Hours Act of 1847"],
        "peter_reforms": ["## Военная реформа", "- В 1705 году", "крепостное право"],
        "peter_dates": ["Азовские походы", "«сверху»"],
        "amir_temur": ["Xoja Ilgʻor", "eʼlon qilindi", "1018 ta yulduzning"],
    }.items():
        text = "\n".join(p.text for p in chunked(key).passages)
        for phrase in expected:
            assert phrase in text, (key, phrase)


def test_a_pdf_page_never_shares_a_passage_with_the_next_page() -> None:
    """§ 3.2.3 rule 2: passages keep their page."""
    passages = chunked("industrial_revolution").passages

    assert [p.page for p in passages] == list(range(1, 9))
    assert passages[3].text.startswith("Steam power.")


def test_docx_sections_are_passages_with_their_heading() -> None:
    """The DOCX headings cut the passages, so a slide can cite one section."""
    passages = chunked("peter_reforms").passages

    assert [p.heading for p in passages] == [
        "Реформы Петра I",
        "Военная реформа",
        "Государственное управление",
        "Экономика",
        "Культура и быт",
        "Итоги реформ",
    ]


# - - - Full context - - -


async def test_all_selected_sources_reach_the_prompt_whole_and_in_order(
    settings: Settings,
) -> None:
    """NB-8: under the cap every passage of every source is sent, S1..S5 in order."""
    sources, passages = stored(ALL, NOTEBOOK)

    pack = await studio_pack(sources, passages, settings, cap=150_000)
    block = render_sources_block(pack)

    assert pack.mode == "full"
    assert [s.title for s in pack.sources] == [SAMPLES[k].title for k in ALL]
    positions = [block.index(f'<source id="S{n}"') for n in range(1, 6)]
    assert positions == sorted(positions)
    for key, source in zip(ALL, pack.sources, strict=True):
        sent = "".join(p.text for p in source.passages)
        assert squeezed(sent) == squeezed(chunked(key).text), key
        assert [p.seq for p in source.passages] == list(
            range(1, len(source.passages) + 1)
        )


async def test_labels_resolve_to_the_passages_of_their_source(
    settings: Settings,
) -> None:
    """NB-20: S{n} is the position among the selected sources, P{m} the seq."""
    sources, passages = stored(ALL, NOTEBOOK)

    pack = await studio_pack(sources, passages, settings, cap=150_000)

    assert pack.source_map == {f"S{n}": s.id for n, s in enumerate(sources, 1)}
    assert pack.labels["S3:P2"].heading == "Военная реформа"
    assert pack.labels["S1:P4"].page == 4
    assert "Oʻtror" in "".join(p.text for p in pack.sources[4].passages)


# - - - Large notebooks - - -


async def test_a_large_notebook_is_sampled_from_every_source_in_order(
    settings: Settings,
) -> None:
    """§ 3.3.2: each source gets its share; the book is sampled evenly, in order."""
    sources, passages = with_long_pdf(ALL)
    book = passages[sources[0].id]

    pack = await studio_pack(sources, passages, settings, cap=6_000)

    assert pack.mode == "sample"
    assert all(source.passages for source in pack.sources)
    pages = [p.page for p in pack.sources[0].passages]
    assert pages == sorted(pages) and pages[0] == 1
    assert pages[-1] is not None and pages[-1] >= 30  # the end of the book too
    gaps = [b - a for a, b in zip(pages, pages[1:], strict=False)]
    assert max(gaps) <= 2 * min(gaps) + 1  # evenly spaced
    assert len(pages) < len(book)
    for small in pack.sources[1:]:  # smaller sources than the minimum come whole
        assert len(small.passages) == len(passages[small.source_id])


async def test_the_focus_adds_matching_passages_without_passing_the_cap(
    settings: Settings,
) -> None:
    """§ 3.3.2: the student's focus brings its passages, the cap still holds."""
    sources, passages = with_long_pdf(["industrial_revolution", "peter_reforms"])
    cap = 8_000

    plain = await studio_pack(sources, passages, settings, cap=cap)
    focused = await studio_pack(
        sources, passages, settings, cap=cap, prompt="Luddites knitting frames"
    )

    luddites = [p for p in focused.sources[0].passages if "Luddites" in p.text]
    assert len(luddites) >= 3
    assert sum("Luddites" in p.text for p in plain.sources[0].passages) < len(luddites)
    assert focused.token_estimate <= cap
    seqs = [p.seq for p in focused.sources[0].passages]
    assert seqs == sorted(seqs)


@pytest.mark.parametrize("cap", [3_000, 6_000, 12_000])
async def test_sampled_sources_keep_their_order_and_labels(
    settings: Settings, cap: int
) -> None:
    """NB-20: labels stay S1..S5 whatever the cap."""
    sources, passages = with_long_pdf(ALL)

    pack = await studio_pack(sources, passages, settings, cap=cap)

    assert [s.n for s in pack.sources] == [1, 2, 3, 4, 5]
    for source in pack.sources:
        assert all(p.label.startswith(f"S{source.n}:P") for p in source.passages)
