"""LIB-13: creating a draft material, the uploader snapshot and its validation."""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemKind,
    ItemStatus,
    MaterialLicence,
    SanctionKind,
    UploaderRole,
    Visibility,
)
from app.modules.library.domain.errors import UploadBannedError
from app.modules.library.domain.moderation_entities import Sanction
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi
from tests.fakes.tasks import FakeTaskKicker
from tests.library.materials.helpers import ident

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]


async def test_a_student_creates_a_draft_with_a_snapshot_of_who_they_are(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    physics: UUID,
    load_item: LoadItem,
) -> None:
    """LIB-13: first name, last initial and cohort are stored with the material."""
    view = await library.materials.create_material.execute(
        student, material_data, locale="en"
    )

    item = await load_item(view.card.id)
    assert view.status is ItemStatus.DRAFT
    assert item.kind is ItemKind.MATERIAL
    assert item.status is ItemStatus.DRAFT
    assert item.owner_id == student.user_id
    assert item.created_by == student.user_id
    assert item.material is not None
    assert item.material.uploader_id == student.user_id
    assert item.material.uploader_role is UploaderRole.STUDENT
    assert item.material.uploader_name == "Aziza K."
    assert item.material.uploader_cohort == "2025"
    assert item.author_label == "Aziza K., 2025"
    assert item.material.attested_at is not None
    assert item.material.submitted_at is None
    assert item.slug.startswith("kinematics-cheat-sheet-")
    assert item.visibility is Visibility.LYCEUM
    assert item.download_allowed is True
    assert item.years_of_study == [1]
    assert [s.id for s in view.card.subjects] == [physics]


async def test_a_teacher_is_named_in_full(
    library: LibraryServices,
    teacher: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-13: teachers appear by name, without a cohort."""
    view = await library.materials.create_material.execute(
        teacher, material_data, locale="en"
    )

    item = await load_item(view.card.id)
    assert item.material is not None
    assert item.material.uploader_role is UploaderRole.TEACHER
    assert item.material.uploader_name == "Dilnoza Rahimova"
    assert item.material.uploader_cohort == ""
    assert item.author_label == "Dilnoza Rahimova"


async def test_a_student_librarian_keeps_the_student_form_of_the_name(
    library: LibraryServices,
    librarian: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-13: a librarian who is a student is shown like a student."""
    view = await library.materials.create_material.execute(
        librarian, material_data, locale="en"
    )

    item = await load_item(view.card.id)
    assert item.material is not None
    assert item.material.uploader_role is UploaderRole.LIBRARIAN
    assert item.material.uploader_name == "Sardor T."


@pytest.mark.parametrize(
    ("licence", "expected"),
    [
        (MaterialLicence.ALL_RIGHTS_RESERVED, Visibility.LYCEUM),
        (MaterialLicence.CC_BY, Visibility.PUBLIC),
        (MaterialLicence.CC_BY_NC_SA, Visibility.PUBLIC),
    ],
)
async def test_only_a_teacher_with_a_creative_commons_licence_goes_public(
    library: LibraryServices,
    teacher: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
    licence: MaterialLicence,
    expected: Visibility,
) -> None:
    """LIB-13: `public` needs a teacher and a Creative Commons licence."""
    data = dataclasses.replace(material_data, licence=licence)

    view = await library.materials.create_material.execute(teacher, data, locale="en")

    assert (await load_item(view.card.id)).visibility is expected


async def test_a_student_with_a_creative_commons_licence_stays_in_the_lyceum(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-13: students cannot publish on the internet."""
    data = dataclasses.replace(material_data, licence=MaterialLicence.CC_BY)

    view = await library.materials.create_material.execute(student, data, locale="en")

    assert (await load_item(view.card.id)).visibility is Visibility.LYCEUM


async def test_a_draft_may_be_saved_before_the_attestation(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-13: the checkbox is asked at submit; the draft is saved without it."""
    data = dataclasses.replace(material_data, attested=False)

    view = await library.materials.create_material.execute(student, data, locale="en")

    item = await load_item(view.card.id)
    assert item.material is not None
    assert item.material.attested_at is None


async def test_a_blank_title_is_refused(
    library: LibraryServices, student: Actor, material_data: MaterialData
) -> None:
    """LIB-13: a material needs a title."""
    data = dataclasses.replace(material_data, title="   ")

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_material.execute(student, data, locale="en")

    assert caught.value.params == {"field": "title"}


async def test_an_unknown_subject_is_refused(
    library: LibraryServices, student: Actor, material_data: MaterialData
) -> None:
    """LIB-4: subjects are checked against the academic directory."""
    data = dataclasses.replace(material_data, subject_ids=(new_id(),))

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_material.execute(student, data, locale="en")

    assert caught.value.params == {"field": "subject_ids"}


async def test_an_unknown_topic_is_refused(
    library: LibraryServices, student: Actor, material_data: MaterialData
) -> None:
    """LIB-4: topics are checked against the taxonomy."""
    data = dataclasses.replace(material_data, topic_ids=(new_id(),))

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_material.execute(student, data, locale="en")

    assert caught.value.params == {"field": "topic_ids"}


async def test_topics_are_linked_to_the_whole_material(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    physics: UUID,
    make_topic: Callable[[UUID], Awaitable[UUID]],
    uow_factory: UowFactory,
) -> None:
    """LIB-4: the chosen topics show on the detail page."""
    topic_id = await make_topic(physics)
    data = dataclasses.replace(material_data, topic_ids=(topic_id,))

    view = await library.materials.create_material.execute(student, data, locale="en")

    assert [(t.id, t.name) for t in view.topics] == [(topic_id, "Kinematics")]
    async with uow_factory() as uow:
        links = await uow.items.topic_links([ident(view)])
    assert [link.topic_id for link in links[ident(view)]] == [topic_id]


async def test_search_text_is_the_latin_form_of_title_and_description(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    load_item: LoadItem,
) -> None:
    """LIB-5: a Cyrillic Uzbek title is found by its Latin spelling."""
    data = dataclasses.replace(
        material_data, title="Ўзбек адабиёти", description="Қисқача конспект"
    )

    view = await library.materials.create_material.execute(student, data, locale="en")

    search_text = (await load_item(view.card.id)).search_text
    assert "oʻzbek" in search_text
    assert "qisqacha" in search_text


async def test_creation_is_written_to_the_history(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: the first event of a material is `created`."""
    view = await library.materials.create_material.execute(
        student, material_data, locale="en"
    )

    async with uow_factory() as uow:
        history = await uow.events.history(ident(view))
    assert [(e.kind, e.actor_id) for e in history] == [
        (EventKind.CREATED, student.user_id)
    ]


async def test_markdown_text_is_stored_as_the_primary_file(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    kicker: FakeTaskKicker,
    load_item: LoadItem,
) -> None:
    """LIB-8: a note written in the editor becomes an `md` file and is processed."""
    data = dataclasses.replace(material_data, body_md="# Kinematics\n\nv = s / t")

    view = await library.materials.create_material.execute(student, data, locale="en")

    item = await load_item(view.card.id)
    (item_file,) = item.files
    assert item_file.format is FileFormat.MD
    assert item_file.is_primary is True
    assert files_api.files[item_file.file_id].data == b"# Kinematics\n\nv = s / t"
    assert item.has_text is True
    assert kicker.calls == [
        (
            "library.process_item_file",
            {"item_id": str(item.id), "file_id": str(item_file.file_id)},
        )
    ]


async def test_nothing_is_kicked_before_the_commit(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-8: a material without a text body starts no processing."""
    await library.materials.create_material.execute(student, material_data, locale="en")

    assert kicker.calls == []


async def test_a_banned_user_cannot_start_a_material(
    library: LibraryServices,
    student: Actor,
    material_data: MaterialData,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: the ban answers `library/banned` with the end date."""
    until = clock.now() + timedelta(days=3)
    async with uow_factory() as uow:
        await uow.moderation.add_sanction(
            Sanction(
                id=new_id(),
                user_id=student.user_id,
                kind=SanctionKind.UPLOAD_BAN,
                reason="repeated copyright reports",
                set_by=new_id(),
                created_at=clock.now(),
                until=until,
            )
        )
        await uow.commit()

    with pytest.raises(UploadBannedError) as caught:
        await library.materials.create_material.execute(
            student, material_data, locale="en"
        )

    assert caught.value.params == {"until": until.isoformat()}
