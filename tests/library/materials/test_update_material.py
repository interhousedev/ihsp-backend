"""LIB-13: owners edit title, description, topics and text at any time."""

import dataclasses
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialData, MaterialPatch
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemStatus,
)
from app.modules.library.domain.errors import ItemNotFoundError, NotEditableError
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi
from tests.fakes.tasks import FakeTaskKicker

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]
MakeDraft = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]


async def test_the_owner_edits_the_published_material_without_review(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    load_item: LoadItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: title and description change at any time; the status stays."""
    item_id = await make_draft(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    slug = (await load_item(item_id)).slug

    view = await library.materials.update_material.execute(
        student,
        item_id,
        MaterialPatch(title="  Kinematics: formulas ", description="Updated text"),
        locale="en",
    )

    item = await load_item(item_id)
    assert view.card.title == "Kinematics: formulas"
    assert item.title == "Kinematics: formulas"
    assert item.description == "Updated text"
    assert item.status is ItemStatus.PUBLISHED
    assert item.slug == slug
    assert "formulas" in item.search_text
    async with uow_factory() as uow:
        history = await uow.events.history(item_id)
    assert history[-1].kind is EventKind.EDITED
    assert history[-1].data == {"fields": ["title", "description"]}


async def test_a_patch_without_fields_changes_nothing(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
) -> None:
    """LIB-13: `None` leaves a field alone."""
    item_id = await make_draft(student)
    before = await load_item(item_id)

    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(), locale="en"
    )

    after = await load_item(item_id)
    assert (after.title, after.description) == (before.title, before.description)


async def test_topics_are_replaced_and_checked(
    library: LibraryServices,
    student: Actor,
    physics: UUID,
    make_draft: MakeDraft,
    make_topic: Callable[[UUID], Awaitable[UUID]],
) -> None:
    """LIB-4: new topics replace the old ones; unknown topics are refused."""
    item_id = await make_draft(student)
    topic = await make_topic(physics)

    view = await library.materials.update_material.execute(
        student, item_id, MaterialPatch(topic_ids=(topic,)), locale="en"
    )
    assert [t.id for t in view.topics] == [topic]
    with pytest.raises(ValidationFailedError):
        await library.materials.update_material.execute(
            student, item_id, MaterialPatch(topic_ids=(new_id(),)), locale="en"
        )

    cleared = await library.materials.update_material.execute(
        student, item_id, MaterialPatch(topic_ids=()), locale="en"
    )
    assert cleared.topics == ()


async def test_a_blank_title_is_refused(
    library: LibraryServices, student: Actor, make_draft: MakeDraft
) -> None:
    """LIB-13: a title cannot be erased."""
    item_id = await make_draft(student)

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.update_material.execute(
            student, item_id, MaterialPatch(title=" "), locale="en"
        )

    assert caught.value.params == {"field": "title"}


async def test_a_new_text_body_replaces_the_old_file(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    kicker: FakeTaskKicker,
    load_item: LoadItem,
) -> None:
    """LIB-8: the editor saves a new `md` file; the old one is deleted afterwards."""
    created = await library.materials.create_material.execute(
        student, dataclasses.replace(material_data, body_md="old"), locale="en"
    )
    assert created.card.id is not None
    old_file = created.files[0].id
    kicker.calls.clear()

    await library.materials.update_material.execute(
        student, created.card.id, MaterialPatch(body_md="new text"), locale="en"
    )

    item = await load_item(created.card.id)
    (item_file,) = item.files
    assert item_file.format is FileFormat.MD
    assert item_file.file_id != old_file
    assert files_api.files[item_file.file_id].data == b"new text"
    assert files_api.deleted == [old_file]
    assert kicker.names() == ["library.process_item_file"]


@pytest.mark.parametrize(
    "status", [ItemStatus.REJECTED, ItemStatus.UNPUBLISHED, ItemStatus.GONE]
)
async def test_a_closed_material_cannot_be_edited(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    status: ItemStatus,
) -> None:
    """LIB-13: rejected and withdrawn materials are final."""
    item_id = await make_draft(student)
    await set_status(item_id, status)

    with pytest.raises(NotEditableError):
        await library.materials.update_material.execute(
            student, item_id, MaterialPatch(title="New"), locale="en"
        )


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.DRAFT,
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.HELD,
    ],
)
async def test_open_materials_can_be_edited(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    status: ItemStatus,
) -> None:
    """LIB-13: edits are allowed while the material is still in play."""
    item_id = await make_draft(student)
    await set_status(item_id, status)

    view = await library.materials.update_material.execute(
        student, item_id, MaterialPatch(title="Better title"), locale="en"
    )

    assert view.card.title == "Better title"


async def test_somebody_elses_material_is_not_found(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
) -> None:
    """LIB-13: IDOR: a student cannot edit another's material, draft or published."""
    item_id = await make_draft(student)

    with pytest.raises(ItemNotFoundError):
        await library.materials.update_material.execute(
            other_student, item_id, MaterialPatch(title="Mine now"), locale="en"
        )
    await set_status(item_id, ItemStatus.PUBLISHED)
    with pytest.raises(ItemNotFoundError):
        await library.materials.update_material.execute(
            other_student, item_id, MaterialPatch(title="Mine now"), locale="en"
        )


async def test_a_librarian_can_fix_a_published_material_but_not_see_a_draft(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    load_item: LoadItem,
) -> None:
    """LIB-2: librarians edit materials they can see; drafts stay private."""
    item_id = await make_draft(student)
    with pytest.raises(ItemNotFoundError):
        await library.materials.update_material.execute(
            other_librarian, item_id, MaterialPatch(title="Fixed"), locale="en"
        )
    await set_status(item_id, ItemStatus.PUBLISHED)

    await library.materials.update_material.execute(
        other_librarian, item_id, MaterialPatch(title="Fixed"), locale="en"
    )

    item = await load_item(item_id)
    assert item.title == "Fixed"
    assert item.owner_id == student.user_id


# - - - Attestation - - -


async def test_the_owner_ticks_and_clears_the_attestation_on_a_draft(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
    clock: FixedClock,
) -> None:
    """LIB-13: `attested: true` sets `attested_at`, `false` clears it."""
    item_id = await make_draft(student, attested=False)

    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(attested=True), locale="en"
    )
    ticked = (await load_item(item_id)).material
    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(attested=False), locale="en"
    )
    cleared = (await load_item(item_id)).material

    assert ticked is not None and ticked.attested_at == clock.now()
    assert cleared is not None and cleared.attested_at is None


async def test_a_patch_without_attested_keeps_it(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
) -> None:
    """LIB-13: other fields do not touch the attestation."""
    item_id = await make_draft(student)

    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(title="New title"), locale="en"
    )

    material = (await load_item(item_id)).material
    assert material is not None and material.attested_at is not None


async def test_the_attestation_can_change_after_the_librarian_sent_it_back(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    load_item: LoadItem,
) -> None:
    """LIB-13: changes requested -> the student may tick again before resubmitting."""
    item_id = await make_draft(student)
    await set_status(item_id, ItemStatus.CHANGES_REQUESTED)

    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(attested=False), locale="en"
    )

    material = (await load_item(item_id)).material
    assert material is not None and material.attested_at is None


@pytest.mark.parametrize(
    "status", [ItemStatus.PENDING_REVIEW, ItemStatus.PUBLISHED, ItemStatus.HELD]
)
async def test_the_attestation_is_final_once_submitted(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    status: ItemStatus,
) -> None:
    """LIB-13: only drafts and sent-back materials can change the attestation."""
    item_id = await make_draft(student)
    await set_status(item_id, status)

    with pytest.raises(NotEditableError):
        await library.materials.update_material.execute(
            student, item_id, MaterialPatch(attested=False), locale="en"
        )


async def test_a_librarian_cannot_attest_for_the_owner(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
) -> None:
    """LIB-13: the statement is the uploader's own."""
    item_id = await make_draft(student, attested=False)
    await set_status(item_id, ItemStatus.CHANGES_REQUESTED)

    with pytest.raises(ForbiddenError):
        await library.materials.update_material.execute(
            other_librarian, item_id, MaterialPatch(attested=True), locale="en"
        )
