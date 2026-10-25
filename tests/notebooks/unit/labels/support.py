"""Builders and readers shared by the label tests."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.labels import (
    LabelLink,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
    SourceLabel,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.notebooks import NOW

LABELS_TASK = "notebooks.label_sources"


def answer(
    labels: list[tuple[str, str]], assignments: dict[str, list[str]]
) -> dict[str, Any]:
    """A model answer: labels as (name, emoji), key l1, l2, ... in order."""
    return {
        "labels": [
            {"key": f"l{n}", "name": name, "emoji": emoji}
            for n, (name, emoji) in enumerate(labels, start=1)
        ],
        "assignments": [
            {"source": source, "labels": keys} for source, keys in assignments.items()
        ],
    }


async def store_label(
    uow_factory: UowFactory,
    notebook_id: UUID,
    name: str,
    origin: LabelOrigin = LabelOrigin.MANUAL,
    position: int = 1,
) -> SourceLabel:
    """Store a label."""
    label = SourceLabel(new_id(), notebook_id, name, "🏷️", position, origin, NOW)
    async with uow_factory() as uow:
        await uow.labels.add(label)
        await uow.commit()
    return label


async def store_link(
    uow_factory: UowFactory,
    source_id: UUID,
    label_id: UUID,
    origin: LabelOrigin = LabelOrigin.MANUAL,
) -> None:
    """Store a link."""
    async with uow_factory() as uow:
        await uow.labels.add_links([LabelLink(source_id, label_id, origin)])
        await uow.commit()


async def mark_running(uow_factory: UowFactory, run: LabelRun) -> None:
    """Store a run as it is."""
    async with uow_factory() as uow:
        await uow.labels.save_run(run)
        await uow.commit()


async def running(
    uow_factory: UowFactory, notebook_id: UUID, user_id: UUID, at: Any
) -> None:
    """Put the notebook into the `running` state, as `StartLabeling` does."""
    await mark_running(
        uow_factory,
        LabelRun(
            notebook_id, LabelRunStatus.RUNNING, started_at=at, started_by=user_id
        ),
    )


async def names(uow_factory: UowFactory, notebook_id: UUID) -> list[str]:
    """The names of the labels by position."""
    async with uow_factory() as uow:
        return [x.name for x in await uow.labels.list_for_notebook(notebook_id)]


async def linked(uow_factory: UowFactory, source_id: UUID) -> set[str]:
    """The names of the labels on a source."""
    async with uow_factory() as uow:
        source = await uow.sources.get(source_id)
        assert source is not None
        by_id = {
            x.id: x.name for x in await uow.labels.list_for_notebook(source.notebook_id)
        }
    return {by_id[i] for i in source.label_ids}


async def run_of(uow_factory: UowFactory, notebook_id: UUID) -> LabelRun:
    """The stored run state."""
    async with uow_factory() as uow:
        run = await uow.labels.get_run(notebook_id)
    assert run is not None
    return run
