"""G12: the SQL repository of topic labels, their links and the auto run state."""

from datetime import timedelta

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.labels import (
    LabelLink,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
    SourceLabel,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import NOW, make_notebook, make_source

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


def label(
    notebook: Notebook, name: str, position: int = 1, **fields: object
) -> SourceLabel:
    """A label that is not stored."""
    values: dict[str, object] = {
        "id": new_id(),
        "notebook_id": notebook.id,
        "name": name,
        "emoji": "🧬",
        "position": position,
        "origin": LabelOrigin.MANUAL,
        "created_at": NOW,
    }
    values.update(fields)
    return SourceLabel(**values)  # type: ignore[arg-type]


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


async def test_a_label_is_stored_and_read_with_its_source_count(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: the label round-trips; `source_count` counts its links."""
    source = await make_source(uow_factory, notebook)
    cells, energy = label(notebook, "Cells", 1), label(notebook, "Energy", 2)

    async with uow_factory() as uow:
        await uow.labels.add(energy)
        await uow.labels.add(cells)
        await uow.labels.add_links([LabelLink(source.id, cells.id, LabelOrigin.AUTO)])
        await uow.commit()
    async with uow_factory() as uow:
        listed = await uow.labels.list_for_notebook(notebook.id)
        one = await uow.labels.get(cells.id)
        missing = await uow.labels.get(new_id())

    assert [(x.name, x.source_count) for x in listed] == [("Cells", 1), ("Energy", 0)]
    assert one is not None and one.source_count == 1 and one.emoji == "🧬"
    assert one.created_at == NOW and missing is None


async def test_a_name_is_unique_per_notebook_in_any_case(
    uow_factory: UowFactory, notebook: Notebook, student: Actor
) -> None:
    """G12: `unique (notebook_id, lower(name))`; another notebook may reuse it."""
    elsewhere = await make_notebook(uow_factory, student.user_id)
    async with uow_factory() as uow:
        await uow.labels.add(label(notebook, "Cells"))
        await uow.labels.add(label(elsewhere, "cells"))
        await uow.commit()

    with pytest.raises(IntegrityError):
        async with uow_factory() as uow:
            await uow.labels.add(label(notebook, "CELLS", 2))


async def test_save_writes_name_emoji_position_and_origin(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: an edit is persisted."""
    stored = label(notebook, "Cells", origin=LabelOrigin.AUTO)
    async with uow_factory() as uow:
        await uow.labels.add(stored)
        await uow.commit()
    stored.name, stored.emoji, stored.position = "Living", "🦠", 5
    stored.origin = LabelOrigin.MANUAL

    async with uow_factory() as uow:
        await uow.labels.save(stored)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.labels.get(stored.id)

    assert loaded == stored


async def test_the_sources_of_a_list_come_with_their_label_ids_in_one_query(
    uow_factory: UowFactory, notebook: Notebook, db_connection: AsyncConnection
) -> None:
    """G12: `label_ids` in label order; one statement for the whole list."""
    first = await make_source(uow_factory, notebook)
    second = await make_source(uow_factory, notebook)
    bare = await make_source(uow_factory, notebook)
    late, early = label(notebook, "Late", 2), label(notebook, "Early", 1)
    async with uow_factory() as uow:
        await uow.labels.add(late)
        await uow.labels.add(early)
        await uow.labels.add_links(
            [
                LabelLink(first.id, late.id, LabelOrigin.AUTO),
                LabelLink(first.id, early.id, LabelOrigin.MANUAL),
                LabelLink(second.id, late.id, LabelOrigin.AUTO),
            ]
        )
        await uow.commit()
    statements: list[str] = []

    def count(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(db_connection.sync_engine, "before_cursor_execute", count)
    try:
        async with uow_factory() as uow:
            sources = await uow.sources.list_for_notebook(notebook.id)
    finally:
        event.remove(db_connection.sync_engine, "before_cursor_execute", count)

    by_id = {s.id: s.label_ids for s in sources}
    assert by_id == {first.id: [early.id, late.id], second.id: [late.id], bare.id: []}
    assert len([s for s in statements if "FROM notebooks.sources" in s]) == 1


async def test_get_and_get_many_carry_the_label_ids_too(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: every read of a source has `label_ids`."""
    source = await make_source(uow_factory, notebook)
    cells = label(notebook, "Cells")
    async with uow_factory() as uow:
        await uow.labels.add(cells)
        await uow.labels.add_links([LabelLink(source.id, cells.id, LabelOrigin.AUTO)])
        await uow.commit()

    async with uow_factory() as uow:
        one = await uow.sources.get(source.id)
        locked = await uow.sources.get_for_update(source.id)
        many = await uow.sources.get_many([source.id])

    assert one is not None and one.label_ids == [cells.id]
    assert locked is not None and locked.label_ids == [cells.id]
    assert many[0].label_ids == [cells.id]


async def test_replace_links_sets_exactly_the_given_labels(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: old links go, new ones come with the origin."""
    source = await make_source(uow_factory, notebook)
    cells, energy = label(notebook, "Cells", 1), label(notebook, "Energy", 2)
    async with uow_factory() as uow:
        await uow.labels.add(cells)
        await uow.labels.add(energy)
        await uow.labels.add_links([LabelLink(source.id, cells.id, LabelOrigin.AUTO)])
        await uow.labels.replace_links(source.id, [energy.id], LabelOrigin.MANUAL)
        await uow.commit()
    async with uow_factory() as uow:
        links = await uow.labels.links_for_notebook(notebook.id)

    assert links == [LabelLink(source.id, energy.id, LabelOrigin.MANUAL)]


async def test_delete_links_removes_only_the_given_origin_of_the_given_sources(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: the manual link and the other source keep theirs."""
    one = await make_source(uow_factory, notebook)
    two = await make_source(uow_factory, notebook)
    cells, energy = label(notebook, "Cells", 1), label(notebook, "Energy", 2)
    async with uow_factory() as uow:
        await uow.labels.add(cells)
        await uow.labels.add(energy)
        await uow.labels.add_links(
            [
                LabelLink(one.id, cells.id, LabelOrigin.AUTO),
                LabelLink(one.id, energy.id, LabelOrigin.MANUAL),
                LabelLink(two.id, cells.id, LabelOrigin.AUTO),
            ]
        )
        await uow.labels.delete_links([one.id], LabelOrigin.AUTO)
        await uow.labels.delete_links([], LabelOrigin.AUTO)
        await uow.commit()
    async with uow_factory() as uow:
        links = await uow.labels.links_for_notebook(notebook.id)

    assert {(x.source_id, x.label_id) for x in links} == {
        (one.id, energy.id),
        (two.id, cells.id),
    }


async def test_a_repeated_link_is_ignored(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """G12: `add_links` does not fail on an existing pair."""
    source = await make_source(uow_factory, notebook)
    cells = label(notebook, "Cells")
    link = LabelLink(source.id, cells.id, LabelOrigin.AUTO)
    async with uow_factory() as uow:
        await uow.labels.add(cells)
        await uow.labels.add_links([link])
        await uow.labels.add_links([link])
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.labels.links_for_notebook(notebook.id) == [link]


async def test_deleting_a_source_a_label_or_a_notebook_cleans_the_links(
    uow_factory: UowFactory, notebook: Notebook, student: Actor
) -> None:
    """G12: foreign keys cascade; labels of a purged notebook go with it."""
    other = await make_notebook(uow_factory, student.user_id)
    one = await make_source(uow_factory, notebook)
    two = await make_source(uow_factory, notebook)
    cells, energy = label(notebook, "Cells", 1), label(notebook, "Energy", 2)
    purged = label(other, "Purged")
    async with uow_factory() as uow:
        for item in (cells, energy, purged):
            await uow.labels.add(item)
        await uow.labels.add_links(
            [
                LabelLink(one.id, cells.id, LabelOrigin.AUTO),
                LabelLink(two.id, cells.id, LabelOrigin.AUTO),
                LabelLink(two.id, energy.id, LabelOrigin.AUTO),
            ]
        )
        await uow.commit()

    async with uow_factory() as uow:
        await uow.sources.delete(one.id)
        await uow.labels.delete([energy.id])
        assert await uow.notebooks.hard_delete([other.id]) == 1
        await uow.commit()
    async with uow_factory() as uow:
        links = await uow.labels.links_for_notebook(notebook.id)
        remaining = await uow.labels.get(purged.id)

    assert links == [LabelLink(two.id, cells.id, LabelOrigin.AUTO)]
    assert remaining is None


async def test_the_run_state_is_inserted_then_updated(
    uow_factory: UowFactory, notebook: Notebook, student: Actor
) -> None:
    """G12: one row per notebook; `get_run` is None before the first run."""
    async with uow_factory() as uow:
        assert await uow.labels.get_run(notebook.id) is None
    started = LabelRun(
        notebook.id, LabelRunStatus.RUNNING, NOW, None, None, student.user_id
    )
    finished = LabelRun(
        notebook.id,
        LabelRunStatus.FAILED,
        NOW,
        NOW + timedelta(seconds=5),
        "provider",
        student.user_id,
    )

    async with uow_factory() as uow:
        await uow.labels.save_run(started)
        await uow.commit()
    async with uow_factory() as uow:
        first = await uow.labels.get_run(notebook.id)
        await uow.labels.save_run(finished)
        await uow.commit()
    async with uow_factory() as uow:
        second = await uow.labels.get_run(notebook.id)

    assert first == started
    assert second == finished
