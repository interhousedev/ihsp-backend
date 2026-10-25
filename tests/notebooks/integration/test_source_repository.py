"""NB-9, NB-10: sources in PostgreSQL (order, duplicates, selection, sweeps)."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Citation, Notebook, SourceGuide
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_notebook,
    make_source,
    new_source_entity,
)

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


async def test_add_then_get_returns_every_stored_field(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: jsonb fields (ref, origin, citations, guide) and enums round-trip."""
    citation = Citation(
        n=1,
        passage_id=new_id(),
        source_id=new_id(),
        source_title="Biology 10.pdf",
        source_kind=SourceKind.FILE,
        page=4,
        snippet="Chlorophyll absorbs light.",
    )
    source = new_source_entity(
        notebook,
        kind=SourceKind.NOTE,
        title="My note",
        ref={"message_id": str(new_id())},
        ref_key="note:1",
        origin={"subject": "Biology", "lesson_date": "2026-10-01"},
        position=7,
        selected=False,
        status=SourceStatus.FAILED,
        failure=SourceFailure.NO_TEXT,
        body_md="Light and ⟦1⟧.",
        citations=[citation],
        content_hash="b" * 64,
        upstream_version="2026-10-01T09:00:00Z",
        word_count=3,
        char_count=14,
        token_estimate=5,
        passage_count=1,
        guide=SourceGuide(summary="S", key_topics=["a"], questions=["Why?"]),
        guide_status=GuideStatus.READY,
        text_synced_at=NOW,
    )

    async with uow_factory() as uow:
        await uow.sources.add(source)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.sources.get(source.id)
        locked = await uow.sources.get_for_update(source.id)

    assert loaded == source
    assert locked == source
    assert loaded is not None and not loaded.editable


async def test_get_unknown_source_is_none(uow_factory: UowFactory) -> None:
    """NB-9: a missing id gives None."""
    async with uow_factory() as uow:
        assert await uow.sources.get(new_id()) is None
        assert await uow.sources.get_for_update(new_id()) is None


async def test_save_writes_status_and_updated_at_as_given(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: save stores the entity's fields; updated_at is the caller's clock."""
    source = await make_source(
        uow_factory, notebook, status=SourceStatus.PROCESSING, texts=()
    )
    source.status = SourceStatus.READY
    source.failure = None
    source.title = "Renamed"
    source.updated_at = NOW + timedelta(minutes=3)

    async with uow_factory() as uow:
        await uow.sources.save(source)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.sources.get(source.id)

    assert loaded == source


async def test_save_of_a_missing_source_does_nothing(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: saving a deleted source neither raises nor inserts."""
    ghost = new_source_entity(notebook)

    async with uow_factory() as uow:
        await uow.sources.save(ghost)
        assert await uow.sources.get(ghost.id) is None


async def test_delete_removes_the_source_and_leaves_the_shared_text(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: removing a source drops its reach to the passages; others keep theirs.

    The document stays (another notebook may hold it); the purge job removes it
    when nobody does.
    """
    doomed = await make_source(uow_factory, notebook, texts=("A one.", "A two."))
    kept = await make_source(uow_factory, notebook, texts=("B one.",))

    async with uow_factory() as uow:
        await uow.sources.delete(doomed.id)
        await uow.sources.delete(new_id())
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.sources.get(doomed.id) is None
        assert await uow.sources.get(kept.id) is not None
        assert await uow.passages.list_for_sources([doomed.id]) == []
        assert len(await uow.passages.list_for_sources([kept.id])) == 1
        assert await uow.documents.find_by_hash(doomed.content_hash or "") is not None


async def test_list_for_notebook_follows_position(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-9: the list order is the prompt order (`position`), per notebook."""
    other = await make_notebook(uow_factory, student.user_id)
    third = await make_source(uow_factory, notebook, position=30)
    first = await make_source(uow_factory, notebook, position=10)
    second = await make_source(uow_factory, notebook, position=20)
    await make_source(uow_factory, other)

    async with uow_factory() as uow:
        listed = await uow.sources.list_for_notebook(notebook.id)

    assert [s.id for s in listed] == [first.id, second.id, third.id]


async def test_get_many_keeps_the_requested_order_and_skips_missing(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: sources come back in the order of the ids; unknown ids are dropped."""
    a = await make_source(uow_factory, notebook)
    b = await make_source(uow_factory, notebook)
    c = await make_source(uow_factory, notebook)

    async with uow_factory() as uow:
        found = await uow.sources.get_many([c.id, new_id(), a.id, c.id, b.id])
        empty = await uow.sources.get_many([])

    assert [s.id for s in found] == [c.id, a.id, b.id]
    assert empty == []


async def test_counters_of_a_notebook_only_count_usable_chars(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-9: total_chars sums ready and stale sources; positions grow by one."""
    async with uow_factory() as uow:
        assert await uow.sources.count_for_notebook(notebook.id) == 0
        assert await uow.sources.total_chars(notebook.id) == 0
        assert await uow.sources.next_position(notebook.id) == 1
    await make_source(uow_factory, notebook, texts=("x" * 100,))
    await make_source(
        uow_factory, notebook, texts=("y" * 50,), status=SourceStatus.STALE
    )
    await make_source(
        uow_factory, notebook, texts=("z" * 7,), status=SourceStatus.FAILED
    )
    await make_source(uow_factory, notebook, texts=(), status=SourceStatus.PENDING)

    async with uow_factory() as uow:
        assert await uow.sources.count_for_notebook(notebook.id) == 4
        assert await uow.sources.total_chars(notebook.id) == 150
        assert await uow.sources.next_position(notebook.id) == 5


async def test_ref_key_is_unique_per_notebook_but_null_keys_repeat(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-10: one source per file in a notebook; the same file may be in two."""
    key = f"file:{new_id()}"
    await make_source(uow_factory, notebook, kind=SourceKind.FILE, ref_key=key)
    await make_source(uow_factory, notebook, ref_key=None)
    await make_source(uow_factory, notebook, ref_key=None)
    other = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, other, kind=SourceKind.FILE, ref_key=key)

    async with uow_factory() as uow:
        assert await uow.sources.ref_key_exists(notebook.id, key)
        assert not await uow.sources.ref_key_exists(notebook.id, "file:other")
        with pytest.raises(IntegrityError):
            await uow.sources.add(new_source_entity(notebook, ref_key=key))


async def test_set_selected_changes_the_checkbox_of_one_notebook(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-11: select all, some or none; other notebooks and updated_at are untouched."""
    other = await make_notebook(uow_factory, student.user_id)
    a = await make_source(uow_factory, notebook)
    b = await make_source(uow_factory, notebook)
    foreign = await make_source(uow_factory, other)

    async def selection() -> dict[UUID, bool]:
        async with uow_factory() as uow:
            found = await uow.sources.get_many([a.id, b.id, foreign.id])
        return {s.id: s.selected for s in found}

    async with uow_factory() as uow:
        await uow.sources.set_selected(notebook.id, False, [a.id])
        await uow.sources.set_selected(notebook.id, True, [foreign.id])
        await uow.sources.set_selected(notebook.id, True, [])
        await uow.commit()
    assert await selection() == {a.id: False, b.id: True, foreign.id: True}

    async with uow_factory() as uow:
        await uow.sources.set_selected(notebook.id, False, None)
        await uow.commit()
    assert await selection() == {a.id: False, b.id: False, foreign.id: True}

    async with uow_factory() as uow:
        loaded = await uow.sources.get(a.id)
    assert loaded is not None and loaded.updated_at == a.updated_at


async def test_list_by_ref_keys_spans_notebooks_but_not_deleted_ones(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-12: an upstream change finds every live source that points at it."""
    key = f"file:{new_id()}"
    mine = await make_notebook(uow_factory, student.user_id)
    theirs = await make_notebook(uow_factory, other_student.user_id)
    gone = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    a = await make_source(uow_factory, mine, kind=SourceKind.FILE, ref_key=key)
    b = await make_source(uow_factory, theirs, kind=SourceKind.FILE, ref_key=key)
    await make_source(uow_factory, gone, kind=SourceKind.FILE, ref_key=key)
    await make_source(uow_factory, mine, kind=SourceKind.FILE, ref_key="file:x")

    async with uow_factory() as uow:
        found = await uow.sources.list_by_ref_keys([key, "file:missing"])
        none = await uow.sources.list_by_ref_keys([])

    assert {s.id for s in found} == {a.id, b.id}
    assert none == []


async def test_list_for_sweep_pages_by_id_over_kinds_and_statuses(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-12: the sweep walks matching sources in id order, a page at a time."""
    wanted = [
        await make_source(
            uow_factory, notebook, kind=SourceKind.FILE, ref_key=f"file:{n}"
        )
        for n in range(3)
    ]
    wanted.append(
        await make_source(
            uow_factory, notebook, kind=SourceKind.CHAT, status=SourceStatus.STALE
        )
    )
    await make_source(uow_factory, notebook, kind=SourceKind.TEXT)
    await make_source(
        uow_factory, notebook, kind=SourceKind.FILE, status=SourceStatus.FAILED
    )
    kinds = [SourceKind.FILE, SourceKind.CHAT]
    statuses = [SourceStatus.READY, SourceStatus.STALE]

    async with uow_factory() as uow:
        first = await uow.sources.list_for_sweep(
            kinds, statuses, after_id=None, limit=3
        )
        second = await uow.sources.list_for_sweep(
            kinds, statuses, after_id=first[-1].id, limit=3
        )

    assert [s.id for s in first + second] == sorted(s.id for s in wanted)
    assert len(first) == 3 and len(second) == 1


async def test_stuck_processing_returns_old_unfinished_sources_oldest_first(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-13: sources that stay pending or processing past the cutoff are found."""
    cutoff = NOW
    oldest = await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PROCESSING,
        texts=(),
        updated_at=cutoff - timedelta(hours=2),
    )
    older = await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PENDING,
        texts=(),
        updated_at=cutoff - timedelta(hours=1),
    )
    fresh = cutoff + timedelta(minutes=1)
    long_ago = cutoff - timedelta(hours=3)
    for status, updated_at in (
        (SourceStatus.PROCESSING, fresh),
        (SourceStatus.READY, long_ago),
        (SourceStatus.FAILED, long_ago),
    ):
        await make_source(
            uow_factory, notebook, texts=(), status=status, updated_at=updated_at
        )

    async with uow_factory() as uow:
        stuck = await uow.sources.stuck_processing(cutoff, limit=10)
        limited = await uow.sources.stuck_processing(cutoff, limit=1)

    assert [s.id for s in stuck] == [oldest.id, older.id]
    assert [s.id for s in limited] == [oldest.id]
