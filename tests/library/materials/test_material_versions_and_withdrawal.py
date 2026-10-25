"""LIB-13: new versions of a published material, and withdrawing a material."""

import dataclasses
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind, ItemKind, ItemStatus
from app.modules.library.domain.errors import ItemNotFoundError, NotEditableError
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from tests.fakes.library.material_files import MaterialFilesApi
from tests.library.materials.helpers import ident

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]
MakeDraft = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]


@pytest.fixture
async def published_id(
    student: Actor, make_draft: MakeDraft, set_status: SetStatus
) -> UUID:
    """A published material of the student."""
    item_id = await make_draft(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    return item_id


# - - - Versions - - -


async def test_a_version_is_a_new_draft_that_points_at_the_old_one(
    library: LibraryServices,
    student: Actor,
    published_id: UUID,
    material_data: MaterialData,
    load_item: LoadItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: the old version stays published while the new one is prepared."""
    view = await library.materials.create_material_version.execute(
        student, published_id, material_data, locale="en"
    )

    new = await load_item(view.card.id)
    old = await load_item(published_id)
    assert view.status is ItemStatus.DRAFT
    assert new.kind is ItemKind.MATERIAL
    assert new.supersedes_id == published_id
    assert new.owner_id == student.user_id
    assert new.slug != old.slug
    assert old.status is ItemStatus.PUBLISHED
    async with uow_factory() as uow:
        history = await uow.events.history(ident(view))
    assert [e.kind for e in history] == [EventKind.VERSION_ADDED]
    assert history[0].data == {"supersedes": str(published_id)}


async def test_a_version_may_be_saved_without_the_attestation(
    library: LibraryServices,
    student: Actor,
    published_id: UUID,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-13: like a new upload, the checkbox is asked at submit."""
    data = dataclasses.replace(material_data, attested=False)

    view = await library.materials.create_material_version.execute(
        student, published_id, data, locale="en"
    )

    material = (await load_item(view.card.id)).material
    assert material is not None and material.attested_at is None


async def test_a_student_version_waits_in_the_queue_and_the_old_stays_published(
    library: LibraryServices,
    student: Actor,
    published_id: UUID,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: the same path as a new upload; no gap for readers."""
    version = await library.materials.create_material_version.execute(
        student, published_id, material_data, locale="en"
    )
    pdf = files_api.upload(student.user_id)
    await library.materials.attach_material_files.execute(
        student, ident(version), [pdf], locale="en"
    )

    view = await library.materials.submit_material.execute(
        student, ident(version), locale="en"
    )

    assert view.status is ItemStatus.PENDING_REVIEW
    assert (await load_item(published_id)).status is ItemStatus.PUBLISHED


async def test_a_teacher_version_replaces_the_old_one_when_it_publishes(
    library: LibraryServices,
    teacher: Actor,
    make_draft: MakeDraft,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: the old version is unpublished with reason `superseded`."""
    old_id = await make_draft(teacher)
    await library.materials.submit_material.execute(teacher, old_id, locale="en")
    version = await library.materials.create_material_version.execute(
        teacher, old_id, material_data, locale="en"
    )
    pdf = files_api.upload(teacher.user_id)
    await library.materials.attach_material_files.execute(
        teacher, ident(version), [pdf], locale="en"
    )
    assert (await load_item(old_id)).status is ItemStatus.PUBLISHED

    await library.materials.submit_material.execute(
        teacher, ident(version), locale="en"
    )

    old = await load_item(old_id)
    assert (old.status, old.status_reason) == (ItemStatus.UNPUBLISHED, "superseded")
    assert (await load_item(version.card.id)).status is ItemStatus.PUBLISHED


@pytest.mark.parametrize(
    "status",
    [ItemStatus.DRAFT, ItemStatus.PENDING_REVIEW, ItemStatus.HELD, ItemStatus.REJECTED],
)
async def test_only_a_published_material_gets_versions(
    library: LibraryServices,
    student: Actor,
    published_id: UUID,
    material_data: MaterialData,
    set_status: SetStatus,
    status: ItemStatus,
) -> None:
    """LIB-13: other states have their own way to change the file."""
    await set_status(published_id, status)

    with pytest.raises(NotEditableError):
        await library.materials.create_material_version.execute(
            student, published_id, material_data, locale="en"
        )


async def test_one_unfinished_version_at_a_time(
    library: LibraryServices,
    student: Actor,
    published_id: UUID,
    material_data: MaterialData,
) -> None:
    """LIB-13: two parallel versions would both want to replace the old one."""
    await library.materials.create_material_version.execute(
        student, published_id, material_data, locale="en"
    )

    with pytest.raises(NotEditableError):
        await library.materials.create_material_version.execute(
            student, published_id, material_data, locale="en"
        )


async def test_only_the_owner_can_add_a_version(
    library: LibraryServices,
    other_student: Actor,
    published_id: UUID,
    material_data: MaterialData,
) -> None:
    """LIB-13: IDOR: `404`."""
    with pytest.raises(ItemNotFoundError):
        await library.materials.create_material_version.execute(
            other_student, published_id, material_data, locale="en"
        )


# - - - Withdrawal - - -


async def test_withdrawing_a_draft_removes_it_and_its_files(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: a draft never reached anyone, so it disappears with its files."""
    item_id = await make_draft(student)
    file_id = (await load_item(item_id)).files[0].file_id

    await library.materials.withdraw_material.execute(student, item_id)

    async with uow_factory() as uow:
        assert await uow.items.get(item_id) is None
    assert files_api.deleted == [file_id]


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.PUBLISHED,
        ItemStatus.HELD,
    ],
)
async def test_withdrawing_a_live_material_unpublishes_it(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    load_item: LoadItem,
    uow_factory: UowFactory,
    status: ItemStatus,
) -> None:
    """LIB-13: owner withdraws -> unpublished, files kept for the purge job."""
    item_id = await make_draft(student)
    await set_status(item_id, status)

    await library.materials.withdraw_material.execute(student, item_id)

    item = await load_item(item_id)
    assert item.status is ItemStatus.UNPUBLISHED
    assert item.status_reason == "withdrawn_by_owner"
    assert item.files
    async with uow_factory() as uow:
        history = await uow.events.history(item_id)
    assert history[-1].kind is EventKind.UNPUBLISHED
    assert history[-1].data == {"by": "owner"}


@pytest.mark.parametrize("status", [ItemStatus.REJECTED, ItemStatus.UNPUBLISHED])
async def test_withdrawing_a_closed_material_changes_nothing(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    load_item: LoadItem,
    status: ItemStatus,
) -> None:
    """LIB-13: withdrawing twice is harmless."""
    item_id = await make_draft(student)
    await set_status(item_id, status, status_reason="duplicate")

    await library.materials.withdraw_material.execute(student, item_id)

    item = await load_item(item_id)
    assert (item.status, item.status_reason) == (status, "duplicate")


async def test_only_the_owner_can_withdraw(
    library: LibraryServices,
    other_student: Actor,
    published_id: UUID,
    load_item: LoadItem,
) -> None:
    """LIB-13: IDOR: `404`, and nothing changes."""
    with pytest.raises(ItemNotFoundError):
        await library.materials.withdraw_material.execute(other_student, published_id)

    assert (await load_item(published_id)).status is ItemStatus.PUBLISHED
