"""G12: labels by hand: create, rename, delete, set the labels of a source."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.label_errors import (
    LabelDuplicateError,
    LabelNotFoundError,
    LabelsLimitError,
)
from app.modules.notebooks.domain.labels import (
    DEFAULT_LABEL_EMOJI,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_labels import LabelsServices
from app.shared.actor import Actor
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.labels.support import (
    linked,
    mark_running,
    names,
    store_label,
    store_link,
)

import pytest

# - - - Create - - -


async def test_a_label_is_added_after_the_others_as_manual(
    labels: LabelsServices, student: Actor, notebook: Notebook
) -> None:
    """G12: name trimmed, position last, origin manual, no sources yet."""
    first = await labels.create_label.execute(student, notebook.id, "  Cells ", "🧬")
    second = await labels.create_label.execute(student, notebook.id, "Energy", "⚡")

    assert (first.name, first.emoji, first.position) == ("Cells", "🧬", 1)
    assert (second.position, second.origin, second.source_count) == (
        2,
        LabelOrigin.MANUAL,
        0,
    )


async def test_an_empty_emoji_becomes_the_default_tag(
    labels: LabelsServices, student: Actor, notebook: Notebook
) -> None:
    """G12: the label is never shown without a mark."""
    label = await labels.create_label.execute(student, notebook.id, "Cells", "")

    assert label.emoji == DEFAULT_LABEL_EMOJI


@pytest.mark.parametrize(
    ("name", "emoji"), [("", "🧬"), ("   ", "🧬"), ("x" * 41, "🧬"), ("Cells", "e" * 9)]
)
async def test_a_bad_name_or_emoji_is_refused(
    labels: LabelsServices, student: Actor, notebook: Notebook, name: str, emoji: str
) -> None:
    """G12: a name of 1 to 40 characters, an emoji of at most 8."""
    with pytest.raises(InvalidOptionsError):
        await labels.create_label.execute(student, notebook.id, name, emoji)


async def test_the_same_name_in_another_case_is_a_duplicate(
    labels: LabelsServices, student: Actor, notebook: Notebook
) -> None:
    """G12: names are unique per notebook without regard to case."""
    await labels.create_label.execute(student, notebook.id, "Cells", "🧬")

    with pytest.raises(LabelDuplicateError):
        await labels.create_label.execute(student, notebook.id, "cELLS", "🧬")


async def test_a_notebook_holds_twelve_labels_at_most(
    labels: LabelsServices, student: Actor, notebook: Notebook
) -> None:
    """G12: the 13th label is refused with `notebooks/labels-limit`."""
    for n in range(12):
        await labels.create_label.execute(student, notebook.id, f"Topic {n}", "🧬")

    with pytest.raises(LabelsLimitError) as error:
        await labels.create_label.execute(student, notebook.id, "One more", "🧬")

    assert error.value.code == "notebooks/labels-limit"


async def test_a_label_cannot_be_added_to_another_students_notebook(
    labels: LabelsServices, student: Actor, their_notebook: Notebook
) -> None:
    """G12: the same 404 as for a missing notebook."""
    with pytest.raises(NotebookNotFoundError):
        await labels.create_label.execute(student, their_notebook.id, "Cells", "🧬")


# - - - List - - -


async def test_the_list_counts_sources_and_starts_idle(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: `source_count` per label, `auto` idle without a finish time."""
    cells = await store_label(uow_factory, notebook.id, "Cells", position=1)
    await store_label(uow_factory, notebook.id, "Energy", position=2)
    await store_link(uow_factory, source.id, cells.id)

    listing = await labels.list_labels.execute(student, notebook.id)

    assert [(x.name, x.source_count) for x in listing.items] == [
        ("Cells", 1),
        ("Energy", 0),
    ]
    assert listing.auto.status is LabelRunStatus.IDLE
    assert listing.auto.finished_at is None


async def test_a_dead_run_is_listed_as_failed(
    labels: LabelsServices,
    uow_factory: UowFactory,
    clock: FixedClock,
    student: Actor,
    notebook: Notebook,
) -> None:
    """G12: a run `running` for over 10 minutes is shown `failed` / `timeout`."""
    await mark_running(
        uow_factory,
        LabelRun(
            notebook.id,
            LabelRunStatus.RUNNING,
            started_at=clock.now(),
            started_by=student.user_id,
        ),
    )
    fresh = await labels.list_labels.execute(student, notebook.id)
    clock.advance(minutes=11)

    stale = await labels.list_labels.execute(student, notebook.id)

    assert fresh.auto.status is LabelRunStatus.RUNNING
    assert (stale.auto.status, stale.auto.error) == (LabelRunStatus.FAILED, "timeout")


async def test_the_labels_of_another_students_notebook_are_not_listed(
    labels: LabelsServices, student: Actor, their_notebook: Notebook
) -> None:
    """G12: 404 for a notebook that is not the caller's."""
    with pytest.raises(NotebookNotFoundError):
        await labels.list_labels.execute(student, their_notebook.id)


# - - - Update - - -


async def test_editing_an_auto_label_makes_it_manual(
    labels: LabelsServices, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """G12: the next auto run keeps a label the student touched."""
    auto = await store_label(uow_factory, notebook.id, "Cells", LabelOrigin.AUTO)

    changed = await labels.update_label.execute(
        student, notebook.id, auto.id, {"name": "Living cells", "emoji": "🦠"}
    )

    assert (changed.name, changed.emoji, changed.origin) == (
        "Living cells",
        "🦠",
        LabelOrigin.MANUAL,
    )
    listing = await labels.list_labels.execute(student, notebook.id)
    assert listing.items[0].origin is LabelOrigin.MANUAL


async def test_an_empty_edit_changes_nothing(
    labels: LabelsServices, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """G12: no key sent, no change of origin."""
    auto = await store_label(uow_factory, notebook.id, "Cells", LabelOrigin.AUTO)

    changed = await labels.update_label.execute(student, notebook.id, auto.id, {})

    assert (changed.name, changed.origin) == ("Cells", LabelOrigin.AUTO)


async def test_renaming_to_a_name_in_use_is_a_duplicate(
    labels: LabelsServices, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """G12: another label's name, in any case."""
    await store_label(uow_factory, notebook.id, "Cells", position=1)
    energy = await store_label(uow_factory, notebook.id, "Energy", position=2)

    with pytest.raises(LabelDuplicateError):
        await labels.update_label.execute(
            student, notebook.id, energy.id, {"name": "CELLS"}
        )


async def test_a_label_can_change_its_case_or_keep_its_name(
    labels: LabelsServices, uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """G12: the label itself is not a duplicate of itself."""
    cells = await store_label(uow_factory, notebook.id, "Cells")

    changed = await labels.update_label.execute(
        student, notebook.id, cells.id, {"name": "CELLS"}
    )

    assert changed.name == "CELLS"


async def test_an_unknown_field_or_label_is_refused(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """G12: only `name` and `emoji`; the label must belong to the notebook."""
    cells = await store_label(uow_factory, notebook.id, "Cells")
    theirs = await store_label(uow_factory, their_notebook.id, "Theirs")

    with pytest.raises(InvalidOptionsError):
        await labels.update_label.execute(
            student, notebook.id, cells.id, {"origin": "x"}
        )
    with pytest.raises(LabelNotFoundError):
        await labels.update_label.execute(
            student, notebook.id, theirs.id, {"name": "A"}
        )


# - - - Delete - - -


async def test_deleting_a_label_removes_it_from_its_sources(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: links go with the label."""
    cells = await store_label(uow_factory, notebook.id, "Cells")
    await store_link(uow_factory, source.id, cells.id)

    await labels.delete_label.execute(student, notebook.id, cells.id)

    assert await names(uow_factory, notebook.id) == []
    assert await linked(uow_factory, source.id) == set()


async def test_a_label_of_another_notebook_cannot_be_deleted(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """G12: `notebooks/label-not-found`, the other label stays."""
    theirs = await store_label(uow_factory, their_notebook.id, "Theirs")

    with pytest.raises(LabelNotFoundError):
        await labels.delete_label.execute(student, notebook.id, theirs.id)

    assert await names(uow_factory, their_notebook.id) == ["Theirs"]


# - - - Labels of a source - - -


async def test_the_labels_of_a_source_are_replaced_and_marked_manual(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: exactly the given labels, in order, as manual links."""
    cells = await store_label(uow_factory, notebook.id, "Cells", position=1)
    energy = await store_label(uow_factory, notebook.id, "Energy", position=2)
    await store_link(uow_factory, source.id, cells.id, LabelOrigin.AUTO)

    updated = await labels.set_source_labels.execute(
        student, notebook.id, source.id, [energy.id, energy.id]
    )

    assert updated.label_ids == [energy.id]
    async with uow_factory() as uow:
        links = await uow.labels.links_for_notebook(notebook.id)
    assert [(x.label_id, x.origin) for x in links] == [(energy.id, LabelOrigin.MANUAL)]


async def test_a_source_may_lose_all_its_labels(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: an empty list clears the source."""
    cells = await store_label(uow_factory, notebook.id, "Cells")
    await store_link(uow_factory, source.id, cells.id)

    updated = await labels.set_source_labels.execute(
        student, notebook.id, source.id, []
    )

    assert updated.label_ids == []


async def test_a_source_takes_three_labels_at_most(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: four labels are `notebooks/labels-limit`; nothing is changed."""
    made = [
        await store_label(uow_factory, notebook.id, f"Topic {n}", position=n)
        for n in range(4)
    ]

    with pytest.raises(LabelsLimitError):
        await labels.set_source_labels.execute(
            student, notebook.id, source.id, [x.id for x in made]
        )

    assert await linked(uow_factory, source.id) == set()


async def test_a_foreign_label_or_source_is_a_404(
    labels: LabelsServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
    source: Source,
) -> None:
    """G12: labels of another notebook do not exist for this one."""
    theirs = await store_label(uow_factory, their_notebook.id, "Theirs")

    with pytest.raises(LabelNotFoundError):
        await labels.set_source_labels.execute(
            student, notebook.id, source.id, [theirs.id]
        )
    with pytest.raises(NotebookNotFoundError):
        await labels.set_source_labels.execute(
            student, their_notebook.id, source.id, []
        )
