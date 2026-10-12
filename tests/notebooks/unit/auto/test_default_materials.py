"""Default materials: the admin adds them, each subject notebook gets a copy."""

from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from app.modules.notebooks.application.material_target import DefaultMaterialDraft
from app.modules.notebooks.domain.default_materials import (
    MAX_DEFAULT_MATERIALS,
    DefaultMaterialKind,
    default_material_of,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.domain.errors import (
    AutoNotebookReadOnlyError,
    DefaultMaterialExistsError,
    DefaultMaterialInvalidError,
    DefaultMaterialLimitError,
    DefaultMaterialNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.auto.conftest import PAGE, open_subject

import pytest

EMIS = 101
OTHER_EMIS = 202


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """An administrator (uploads the files, sets the default materials)."""
    return make_actor(Role.ADMIN)


@pytest.fixture
def physics_emis(world: World, physics: LessonRef) -> int:
    """The Physics subject has the EMIS id of the tests."""
    world.schedule.set_emis_id(physics.subject_id, EMIS)
    return EMIS


async def _sources(uow_factory: UowFactory, notebook_id: UUID) -> list[Source]:
    async with uow_factory() as uow:
        return await uow.sources.list_for_notebook(notebook_id)


def _admin_file(world: World, admin: Actor, name: str = "Guide.pdf") -> UUID:
    """A file the admin uploaded, with readable text."""
    return world.files.add_text(make_file(admin.user_id, name=name), PAGE).id


def _file(file_id: UUID, title: str = "Guide") -> DefaultMaterialDraft:
    return DefaultMaterialDraft(
        kind=DefaultMaterialKind.FILE, title=title, file_id=file_id
    )


def _link(url: str, title: str = "Khan") -> DefaultMaterialDraft:
    return DefaultMaterialDraft(kind=DefaultMaterialKind.LINK, title=title, url=url)


async def test_a_file_default_material_is_copied_into_every_subject_notebook(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    other_student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """Each student's notebook of the subject gets the file, marked as its copy."""
    world.schedule.attend(other_student.user_id, physics)
    material = await auto.add_default_material.execute(
        admin, physics_emis, _file(_admin_file(world, admin))
    )

    notebook = await open_subject(auto, student, physics)
    [copy] = await _sources(uow_factory, notebook.id)
    other = await open_subject(auto, other_student, physics)
    [other_copy] = await _sources(uow_factory, other.id)

    assert copy.kind is SourceKind.FILE
    assert copy.title == "Guide"
    assert default_material_of(copy) == str(material.id)
    assert other_copy.ref_key == copy.ref_key


async def test_a_resync_does_not_copy_a_default_material_twice(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """Idempotent: the copy is there, so the next sync adds nothing."""
    await auto.add_default_material.execute(
        admin, physics_emis, _file(_admin_file(world, admin))
    )
    notebook = await open_subject(auto, student, physics)

    again = await auto.sync_auto_notebook.execute(notebook.id)

    assert (again.added, again.removed) == (0, 0)
    assert len(await _sources(uow_factory, notebook.id)) == 1


async def test_a_link_default_material_is_a_url_source_with_its_normalised_address(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """A link is copied as the student's own URL source would be."""
    await auto.add_default_material.execute(
        admin, physics_emis, _link("https://Khan.org/physics#top")
    )

    notebook = await open_subject(auto, student, physics)

    [copy] = await _sources(uow_factory, notebook.id)
    assert copy.kind is SourceKind.URL
    assert copy.ref == {"url": "https://khan.org/physics"}


async def test_a_library_default_material_is_a_library_source(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """A library book is read for the student like one they added themselves."""
    book = world.library.add_book("Physics 10")
    await auto.add_default_material.execute(
        admin,
        physics_emis,
        DefaultMaterialDraft(
            kind=DefaultMaterialKind.LIBRARY_ITEM,
            title="Physics 10",
            library_item_id=book.id,
        ),
    )

    notebook = await open_subject(auto, student, physics)

    [copy] = await _sources(uow_factory, notebook.id)
    assert copy.kind is SourceKind.LIBRARY_ITEM
    assert copy.ref["item_id"] == str(book.id)


async def test_defaults_of_other_subjects_and_lesson_notebooks_do_not_apply(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """Only the subject with the EMIS id gets them, and lesson notebooks never do."""
    await auto.add_default_material.execute(
        admin, OTHER_EMIS, _file(_admin_file(world, admin))
    )

    notebook = await open_subject(auto, student, physics)
    lesson_notebook = await auto.open_auto_notebook.execute(
        student, NotebookOrigin.LESSON_AUTO, physics.id
    )

    assert await _sources(uow_factory, notebook.id) == []
    assert await _sources(uow_factory, lesson_notebook.id) == []


async def test_a_file_without_text_is_copied_once_it_is_ready(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """A file still processing is skipped; the next sync after it has text copies it."""
    pending = world.files.add(
        make_file(admin.user_id, name="Guide.pdf", text_bytes=None)
    )
    await auto.add_default_material.execute(admin, physics_emis, _file(pending.id))
    notebook = await open_subject(auto, student, physics)
    assert await _sources(uow_factory, notebook.id) == []

    world.files.add_text(replace(pending, text_bytes=2000), PAGE)
    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.added == 1
    assert len(await _sources(uow_factory, notebook.id)) == 1


async def test_removing_a_default_material_takes_its_copies_out_on_sync(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
) -> None:
    """The copy is managed like a lesson material: the next sync removes it."""
    material = await auto.add_default_material.execute(
        admin, physics_emis, _file(_admin_file(world, admin))
    )
    notebook = await open_subject(auto, student, physics)

    await auto.remove_default_material.execute(physics_emis, material.id)
    result = await auto.sync_auto_notebook.execute(notebook.id)

    assert result.removed == 1
    assert await _sources(uow_factory, notebook.id) == []


async def test_an_excluded_default_copy_stays_out_and_cannot_be_removed_directly(
    auto: AutoServices,
    uow_factory: UowFactory,
    world: World,
    admin: Actor,
    student: Actor,
    physics: LessonRef,
    physics_emis: int,
    sources: SourcesServices,
) -> None:
    """Excluding a copy keeps it out on later syncs; deleting it is refused."""
    await auto.add_default_material.execute(
        admin, physics_emis, _link("https://khan.org/physics")
    )
    notebook = await open_subject(auto, student, physics)
    [copy] = await _sources(uow_factory, notebook.id)

    with pytest.raises(AutoNotebookReadOnlyError):
        await sources.remove_source.execute(student, notebook.id, copy.id)

    await auto.update_auto_settings.execute(
        student, notebook.id, {"exclude_source_ids": [copy.id]}
    )
    await auto.sync_auto_notebook.execute(notebook.id)

    assert await _sources(uow_factory, notebook.id) == []


async def test_the_admin_gets_refusals_for_bad_files_links_and_repeats(
    auto: AutoServices,
    world: World,
    admin: Actor,
    student: Actor,
    physics_emis: int,
) -> None:
    """Only the admin's own files, valid links, no repeats, and a limit per subject."""
    foreign = world.files.add_text(make_file(student.user_id, name="notes.pdf"), PAGE)
    with pytest.raises(DefaultMaterialInvalidError):
        await auto.add_default_material.execute(admin, physics_emis, _file(foreign.id))
    with pytest.raises(DefaultMaterialInvalidError):
        await auto.add_default_material.execute(admin, physics_emis, _file(new_id()))
    with pytest.raises(DefaultMaterialInvalidError):
        await auto.add_default_material.execute(
            admin, physics_emis, _link("ftp://example.com/file")
        )

    await auto.add_default_material.execute(
        admin, physics_emis, _link("https://example.com/a")
    )
    with pytest.raises(DefaultMaterialExistsError):
        await auto.add_default_material.execute(
            admin, physics_emis, _link("https://example.com/a", title="again")
        )
    for number in range(1, MAX_DEFAULT_MATERIALS):
        await auto.add_default_material.execute(
            admin, physics_emis, _link(f"https://example.com/{number}")
        )
    with pytest.raises(DefaultMaterialLimitError):
        await auto.add_default_material.execute(
            admin, physics_emis, _link("https://example.com/last")
        )


async def test_a_default_material_is_removed_only_from_its_own_subject(
    auto: AutoServices,
    world: World,
    admin: Actor,
    physics_emis: int,
) -> None:
    """Removing it under another EMIS id is not found; under its own it works."""
    material = await auto.add_default_material.execute(
        admin, physics_emis, _link("https://example.com/only")
    )

    with pytest.raises(DefaultMaterialNotFoundError):
        await auto.remove_default_material.execute(OTHER_EMIS, material.id)

    await auto.remove_default_material.execute(physics_emis, material.id)
    remaining = await auto.list_default_materials.execute(physics_emis)
    assert remaining == []
