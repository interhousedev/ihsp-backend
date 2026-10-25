"""NB-1, NB-2: notebooks in PostgreSQL (lists, counters, soft delete, cascades)."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    ChatConfig,
    Notebook,
    NotebookSummary,
)
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ChatLanguage,
    ChatStyle,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.notebook_repository import NotebookCursor
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_artifact,
    make_message,
    make_notebook,
    make_source,
    new_notebook_entity,
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _cursor(notebook: Notebook) -> NotebookCursor:
    return NotebookCursor(notebook.pinned, notebook.last_opened_at, notebook.id)


async def _count(session: AsyncSession, table: str, notebook_id: UUID) -> int:
    key = "id" if table == "notebooks" else "notebook_id"
    sql = f"SELECT count(*) FROM notebooks.{table} WHERE {key} = :id"  # noqa: S608
    return int((await session.execute(text(sql), {"id": notebook_id})).scalar_one())


async def test_add_then_get_returns_every_stored_field(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-1: jsonb fields (chat config, summary) survive a round trip."""
    summary = NotebookSummary(
        summary="Plants make sugar.",
        key_topics=["light"],
        suggested_questions=["Why?"],
        generated_at=NOW,
    )
    stored = await make_notebook(
        uow_factory,
        student.user_id,
        emoji="🌱",
        emoji_auto=False,
        title_auto=False,
        pinned=True,
        chat_config=ChatConfig(
            style=ChatStyle.CUSTOM, custom_prompt="Be brief", language=ChatLanguage.UZ
        ),
        summary=summary,
        summary_status=SummaryStatus.READY,
        summary_hash="a" * 64,
        source_count=3,
        char_count=12_000_000_000,
        last_opened_at=NOW,
    )

    async with uow_factory() as uow:
        loaded = await uow.notebooks.get(stored.id)

    assert loaded == stored


async def test_get_unknown_notebook_is_none(uow_factory: UowFactory) -> None:
    """NB-1: a missing id gives None, not an error."""
    async with uow_factory() as uow:
        assert await uow.notebooks.get(new_id()) is None
        assert await uow.notebooks.get_for_update(new_id()) is None


async def test_get_counts_ready_and_selected_ready_sources(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: ready_source_count counts ready and stale sources; selected needs both."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook, status=SourceStatus.READY)
    await make_source(uow_factory, notebook, status=SourceStatus.STALE, selected=False)
    await make_source(uow_factory, notebook, status=SourceStatus.PENDING, texts=())
    await make_source(uow_factory, notebook, status=SourceStatus.FAILED, texts=())

    async with uow_factory() as uow:
        got = await uow.notebooks.get(notebook.id)
        locked = await uow.notebooks.get_for_update(notebook.id)
        listed = await uow.notebooks.list_for_owner(
            student.user_id, query=None, after=None, limit=10
        )

    assert got is not None and locked is not None
    assert (got.ready_source_count, got.selected_source_count) == (2, 1)
    assert (locked.ready_source_count, locked.selected_source_count) == (2, 1)
    assert [(n.ready_source_count, n.selected_source_count) for n in listed] == [(2, 1)]


async def test_save_writes_changes_and_ignores_the_counters(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-1: save updates stored fields; the derived counts come from sources."""
    notebook = await make_notebook(uow_factory, student.user_id)
    notebook.title = "Renamed"
    notebook.title_auto = False
    notebook.summary_status = SummaryStatus.STALE
    notebook.summary_due_at = NOW + timedelta(seconds=20)
    notebook.deleted_at = NOW
    notebook.ready_source_count = 99

    async with uow_factory() as uow:
        await uow.notebooks.save(notebook)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.notebooks.get(notebook.id)

    assert loaded is not None
    assert loaded.title == "Renamed"
    assert not loaded.title_auto
    assert loaded.summary_status is SummaryStatus.STALE
    assert loaded.summary_due_at == NOW + timedelta(seconds=20)
    assert loaded.is_deleted
    assert loaded.ready_source_count == 0


async def test_save_of_a_missing_notebook_does_nothing(
    uow_factory: UowFactory,
) -> None:
    """NB-1: saving an entity that was hard-deleted neither raises nor inserts."""
    ghost = new_notebook_entity()

    async with uow_factory() as uow:
        await uow.notebooks.save(ghost)
        assert await uow.notebooks.get(ghost.id) is None


async def test_count_live_skips_deleted_and_other_owners(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-1: the notebook limit counts only the owner's live notebooks."""
    await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    await make_notebook(uow_factory, other_student.user_id)

    async with uow_factory() as uow:
        assert await uow.notebooks.count_live(student.user_id) == 2
        assert await uow.notebooks.count_live(new_id()) == 0


async def test_list_orders_pinned_first_then_last_opened_with_nulls_last(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-2: pinned, last_opened_at desc nulls last, then newest id; no foreign rows."""
    day = timedelta(days=1)
    pinned_old = await make_notebook(
        uow_factory, student.user_id, pinned=True, last_opened_at=NOW - 3 * day
    )
    pinned_new = await make_notebook(
        uow_factory, student.user_id, pinned=True, last_opened_at=NOW - day
    )
    pinned_never = await make_notebook(uow_factory, student.user_id, pinned=True)
    recent = await make_notebook(uow_factory, student.user_id, last_opened_at=NOW)
    older = await make_notebook(
        uow_factory, student.user_id, last_opened_at=NOW - 2 * day
    )
    never_first = await make_notebook(uow_factory, student.user_id)
    never_second = await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    await make_notebook(uow_factory, other_student.user_id, pinned=True)

    async with uow_factory() as uow:
        listed = await uow.notebooks.list_for_owner(
            student.user_id, query=None, after=None, limit=50
        )

    assert [n.id for n in listed] == [
        pinned_new.id,
        pinned_old.id,
        pinned_never.id,
        recent.id,
        older.id,
        never_second.id,
        never_first.id,
    ]


async def test_cursor_pages_add_up_to_the_whole_list(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: following the cursor visits every notebook once, in list order."""
    day = timedelta(days=1)
    for index in range(4):
        await make_notebook(
            uow_factory,
            student.user_id,
            pinned=index % 2 == 0,
            last_opened_at=None if index in (1, 2) else NOW - index * day,
        )
    for index in range(3):
        await make_notebook(uow_factory, student.user_id, last_opened_at=None)
        await make_notebook(
            uow_factory, student.user_id, last_opened_at=NOW - index * day
        )
    async with uow_factory() as uow:
        whole = await uow.notebooks.list_for_owner(
            student.user_id, query=None, after=None, limit=50
        )

    for page_size in (1, 2, 3, 5):
        seen: list[UUID] = []
        after: NotebookCursor | None = None
        while True:
            async with uow_factory() as uow:
                page = await uow.notebooks.list_for_owner(
                    student.user_id, query=None, after=after, limit=page_size
                )
            seen.extend(n.id for n in page)
            if len(page) < page_size:
                break
            after = _cursor(page[-1])
        assert seen == [n.id for n in whole], page_size


async def test_list_filters_by_title_ignoring_case_and_like_wildcards(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: the search box is a case-insensitive substring; % and _ are literal."""
    wanted = await make_notebook(uow_factory, student.user_id, title="100% Biology")
    await make_notebook(uow_factory, student.user_id, title="100 Chemistry")
    await make_notebook(uow_factory, student.user_id, title="A_B and more")
    await make_notebook(uow_factory, student.user_id, title="AxB and more")

    async with uow_factory() as uow:
        by_case = await uow.notebooks.list_for_owner(
            student.user_id, query="biolo", after=None, limit=10
        )
        by_percent = await uow.notebooks.list_for_owner(
            student.user_id, query="100%", after=None, limit=10
        )
        by_underscore = await uow.notebooks.list_for_owner(
            student.user_id, query="a_b", after=None, limit=10
        )

    assert [n.id for n in by_case] == [wanted.id]
    assert [n.id for n in by_percent] == [wanted.id]
    assert [n.title for n in by_underscore] == ["A_B and more"]


async def test_due_summaries_returns_stale_notebooks_that_are_due(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-4: only live notebooks with a stale summary due now, most overdue first."""
    due = NOW - timedelta(seconds=5)
    late = await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.STALE,
        summary_due_at=due,
    )
    later = await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.STALE,
        summary_due_at=NOW,
    )
    for fields in (
        {"summary_status": SummaryStatus.STALE, "summary_due_at": NOW + timedelta(1)},
        {"summary_status": SummaryStatus.READY, "summary_due_at": due},
        {"summary_status": SummaryStatus.BUILDING, "summary_due_at": due},
        {
            "summary_status": SummaryStatus.STALE,
            "summary_due_at": due,
            "deleted_at": NOW,
        },
    ):
        await make_notebook(uow_factory, student.user_id, **fields)

    async with uow_factory() as uow:
        found = await uow.notebooks.due_summaries(NOW, limit=10)
        limited = await uow.notebooks.due_summaries(NOW, limit=1)

    assert [n.id for n in found] == [late.id, later.id]
    assert [n.id for n in limited] == [late.id]


async def test_due_summaries_skips_rows_locked_by_another_worker(
    engine: AsyncEngine,
) -> None:
    """NB-4: two workers never take the same notebook (FOR UPDATE SKIP LOCKED)."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def open_uow() -> SqlNotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(maker, noop_outbox_writer, noop_audit_writer)

    owner = new_id()
    first = new_notebook_entity(
        owner,
        summary_status=SummaryStatus.STALE,
        summary_due_at=NOW - timedelta(minutes=2),
    )
    second = new_notebook_entity(
        owner,
        summary_status=SummaryStatus.STALE,
        summary_due_at=NOW - timedelta(minutes=1),
    )
    async with open_uow() as uow:
        await uow.notebooks.add(first)
        await uow.notebooks.add(second)
        await uow.commit()
    try:
        async with open_uow() as worker_a, open_uow() as worker_b:
            taken_by_a = await worker_a.notebooks.due_summaries(NOW, limit=1)
            ours = {first.id, second.id}
            taken_by_b = await worker_b.notebooks.due_summaries(NOW, limit=500)
        assert len(taken_by_a) == 1
        assert taken_by_a[0].id in ours
        assert taken_by_a[0].id not in {n.id for n in taken_by_b}
        assert (ours - {taken_by_a[0].id}) <= {n.id for n in taken_by_b}
    finally:
        async with open_uow() as uow:
            await uow.notebooks.hard_delete([first.id, second.id])
            await uow.commit()


async def test_deleted_before_and_ids_for_owner(
    uow_factory: UowFactory, student: Actor, other_student: Actor
) -> None:
    """NB-3: purge candidates are notebooks soft-deleted before the cutoff."""
    week = timedelta(days=7)
    old = await make_notebook(uow_factory, student.user_id, deleted_at=NOW - 2 * week)
    older = await make_notebook(uow_factory, student.user_id, deleted_at=NOW - 3 * week)
    just_now = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    live = await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, other_student.user_id, deleted_at=NOW - 4 * week)

    async with uow_factory() as uow:
        cutoff = NOW - week
        purge = await uow.notebooks.deleted_before(cutoff, limit=100)
        limited = await uow.notebooks.deleted_before(cutoff, limit=1)
        mine = await uow.notebooks.ids_for_owner(student.user_id)

    assert purge.index(older.id) < purge.index(old.id)
    assert just_now.id not in purge and live.id not in purge
    assert limited == purge[:1]
    assert sorted(mine) == sorted([old.id, older.id, just_now.id, live.id])


async def test_hard_delete_removes_everything_the_notebook_owns(
    uow_factory: UowFactory, db_session: AsyncSession, student: Actor
) -> None:
    """NB-3: deleting a notebook cascades to sources, chat and outputs.

    The passages belong to shared documents: they stay for the notebook that still
    holds the same texts (the purge job removes documents nobody holds).
    """
    doomed = await make_notebook(uow_factory, student.user_id)
    kept = await make_notebook(uow_factory, student.user_id)
    for notebook in (doomed, kept):
        await make_source(uow_factory, notebook, texts=("One.", "Two.", "Three."))
        await make_message(uow_factory, notebook)
        await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)

    async with uow_factory() as uow:
        removed = await uow.notebooks.hard_delete([doomed.id, new_id()])
        nothing = await uow.notebooks.hard_delete([])
        await uow.commit()

    assert (removed, nothing) == (1, 0)
    for table in ("notebooks", "sources", "messages", "artifacts"):
        assert await _count(db_session, table, doomed.id) == 0, table
        assert await _count(db_session, table, kept.id) >= 1, table
    async with uow_factory() as uow:
        survivors = await uow.sources.list_for_notebook(kept.id)
        assert len(await uow.passages.list_for_sources([survivors[0].id])) == 3
