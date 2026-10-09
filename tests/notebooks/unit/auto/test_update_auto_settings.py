"""NB-AUTO: classmates' files, excluded materials and the read-only rules."""

from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import (
    AutoNotebookReadOnlyError,
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.source_input import (
    NoteInput,
    TextInput,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import open_subject, teacher_file

import pytest


async def _sources(uow_factory: UowFactory, notebook: Notebook) -> list[Source]:
    async with uow_factory() as uow:
        return await uow.sources.list_for_notebook(notebook.id)


async def test_an_excluded_material_leaves_and_stays_out_on_every_sync(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: exclude is allowed and a re-sync does not bring the file back."""
    keep = teacher_file(world, physics, "Keep")
    drop = teacher_file(world, physics, "Drop")
    notebook = await open_subject(auto, student, physics)
    dropped = next(
        s
        for s in await _sources(uow_factory, notebook)
        if s.ref_key == f"lesson:{drop}"
    )

    updated = await auto.update_auto_settings.execute(
        student, notebook.id, {"exclude_source_ids": [dropped.id]}
    )
    await auto.sync_auto_notebook.execute(notebook.id)
    await auto.sync_auto_notebook.execute(notebook.id)

    assert [s.ref_key for s in await _sources(uow_factory, notebook)] == [
        f"lesson:{keep}"
    ]
    assert updated.auto_settings is not None
    [excluded] = updated.auto_settings.excluded_refs
    assert (excluded.ref_key, excluded.title) == (f"lesson:{drop}", "Drop")
    assert updated.source_count == 1


async def test_a_restored_material_comes_back(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: taking an excluded material back adds it again at once."""
    link = teacher_file(world, physics, "Drop")
    notebook = await open_subject(auto, student, physics)
    [source] = await _sources(uow_factory, notebook)
    await auto.update_auto_settings.execute(
        student, notebook.id, {"exclude_source_ids": [source.id]}
    )

    restored = await auto.update_auto_settings.execute(
        student, notebook.id, {"restore_refs": [f"lesson:{link}"]}
    )

    assert restored.auto_settings is not None
    assert restored.auto_settings.excluded_refs == []
    assert [s.ref_key for s in await _sources(uow_factory, notebook)] == [
        f"lesson:{link}"
    ]


async def test_excluding_twice_or_a_stranger_changes_nothing(
    auto: AutoServices,
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
    their_notebook: Notebook,
) -> None:
    """NB-AUTO: ids of notes, of other notebooks and unknown ids are ignored."""
    teacher_file(world, physics)
    notebook = await open_subject(auto, student, physics)
    [material] = await _sources(uow_factory, notebook)
    note = (
        await sources.add_sources.execute(
            student, notebook.id, [NoteInput(title="N", body_md="text")]
        )
    ).items[0]

    result = await auto.update_auto_settings.execute(
        student,
        notebook.id,
        {"exclude_source_ids": [material.id, material.id, note.id, new_id()]},
    )

    assert result.auto_settings is not None
    assert len(result.auto_settings.excluded_refs) == 1
    assert note.id in {s.id for s in await _sources(uow_factory, notebook)}


async def test_unknown_keys_and_bad_values_are_refused_without_saving(
    auto: AutoServices, student: Actor, physics: LessonRef
) -> None:
    """NB-AUTO: a typo is an error, not a silent no-op."""
    notebook = await open_subject(auto, student, physics)

    for bad in (
        {"title": "x"},
        {"include_classmates": "yes"},
        {"exclude_source_ids": "x"},
        {"exclude_source_ids": ["not-a-uuid"]},
        {"restore_refs": [1]},
    ):
        with pytest.raises(InvalidOptionsError):
            await auto.update_auto_settings.execute(student, notebook.id, bad)


async def test_only_an_auto_notebook_of_the_caller_has_these_settings(
    auto: AutoServices,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
    notebook: Notebook,
    world: World,
) -> None:
    """NB-AUTO: a manual notebook has none; someone else's notebook is a 404."""
    mine = await open_subject(auto, student, physics)

    with pytest.raises(InvalidOptionsError):
        await auto.update_auto_settings.execute(
            student, notebook.id, {"include_classmates": True}
        )
    with pytest.raises(NotebookNotFoundError):
        await auto.update_auto_settings.execute(
            other_student, mine.id, {"include_classmates": True}
        )


async def test_lesson_materials_cannot_be_added_by_hand(
    auto: AutoServices,
    sources: SourcesServices,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: auto notebooks are read-only for sources; only notes can be added."""
    notebook = await open_subject(auto, student, physics)

    with pytest.raises(AutoNotebookReadOnlyError):
        await sources.add_sources.execute(
            student, notebook.id, [TextInput(title="Pasted", text="Some text.")]
        )
    added = await sources.add_sources.execute(
        student, notebook.id, [NoteInput(title="Mine", body_md="A note.")]
    )

    assert len(added.items) == 1 and added.rejected == []


async def test_a_lesson_material_cannot_be_removed_but_a_note_can(
    auto: AutoServices,
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: removing would be undone by the next sync, so it is refused."""
    teacher_file(world, physics)
    notebook = await open_subject(auto, student, physics)
    [material] = await _sources(uow_factory, notebook)
    note = (
        await sources.add_sources.execute(
            student, notebook.id, [NoteInput(title="N", body_md="text")]
        )
    ).items[0]

    with pytest.raises(AutoNotebookReadOnlyError):
        await sources.remove_source.execute(student, notebook.id, material.id)
    await sources.remove_source.execute(student, notebook.id, note.id)

    remaining: list[UUID] = [s.id for s in await _sources(uow_factory, notebook)]
    assert remaining == [material.id]
