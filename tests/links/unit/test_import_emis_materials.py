"""ACA-9: EMIS materials are downloaded into our storage and attached as files."""

from uuid import UUID

from app.modules.academic.application.schedule.import_materials import (
    ImportLessonMaterials,
)
from app.modules.academic.application.schedule.ports.lesson_urls import EmisMaterial
from app.modules.files.domain.errors import TypeNotAllowedError
from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.contracts.emis import EmisFile
from app.shared.contracts.files import FileScope
from app.shared.contracts.links import EMIS_AUTHOR_ID
from app.shared.ids import new_id
from tests.fakes.academic.schedule.emis import FakeEmisSource
from tests.fakes.links.world import LinksWorld
from tests.links.unit.test_lesson_resources import Class

TOPIC = "https://cdn-emis.edu.uz/files/a"
HOMEWORK = "https://cdn-emis.edu.uz/files/b.docx"
VIDEO = "https://www.youtube.com/watch?v=q0sUmfmG7gI"
PDF = b"%PDF-1.4 tiny"
READER = new_id()


def importer(world: LinksWorld, emis: FakeEmisSource) -> ImportLessonMaterials:
    return ImportLessonMaterials(
        emis=emis, files=world.files, links=world.services.public, max_bytes=1000
    )


def scripted() -> FakeEmisSource:
    emis = FakeEmisSource()
    emis.files[TOPIC] = EmisFile("lesson.pdf", "application/pdf", PDF)
    emis.files[HOMEWORK] = EmisFile("b.docx", None, b"PK\x03\x04docx")
    return emis


def materials(lesson_id: UUID) -> list[EmisMaterial]:
    return [
        EmisMaterial(lesson_id, TOPIC, "Jadids", "classwork"),
        EmisMaterial(lesson_id, HOMEWORK, "Jadids", "homework"),
        EmisMaterial(lesson_id, VIDEO, "Jadids", "video"),
    ]


async def test_downloads_become_emis_file_resources_with_a_prefix(
    world: LinksWorld,
) -> None:
    """Classwork and homework files are stored in S3; the video stays a link."""
    c = Class(world)
    emis = scripted()

    added = await importer(world, emis).import_materials(READER, materials(c.lesson.id))

    assert added == 3
    refs = await world.services.public.lesson_resources(c.lesson.id)
    assert [(r.title, r.kind, r.source, r.author_id) for r in refs] == [
        ("Classwork: Jadids.pdf", "file", "emis", EMIS_AUTHOR_ID),
        ("Homework: Jadids.docx", "file", "emis", EMIS_AUTHOR_ID),
        ("Jadids (video)", "url", "emis", EMIS_AUTHOR_ID),
    ]
    stored = [world.files.files[r.file_id] for r in refs if r.file_id]
    assert {f.scope for f in stored} == {FileScope.SYSTEM}
    assert sorted(world.files.objects.values()) == sorted([PDF, b"PK\x03\x04docx"])
    assert emis.downloads == [(READER, TOPIC), (READER, HOMEWORK)]


async def test_a_failed_download_falls_back_to_a_link(world: LinksWorld) -> None:
    """EMIS down (or the file refused): the student still gets the address."""
    c = Class(world)
    emis = FakeEmisSource()  # knows no file: every download fails

    added = await importer(world, emis).import_materials(
        READER, materials(c.lesson.id)[:2]
    )

    assert added == 2
    refs = await world.services.public.lesson_resources(c.lesson.id)
    assert [(r.title, r.kind) for r in refs] == [
        ("Classwork: Jadids", "url"),
        ("Homework: Jadids", "url"),
    ]
    assert world.files.objects == {}


async def test_a_refused_file_type_falls_back_to_a_link(world: LinksWorld) -> None:
    """The upload checks run; a type they refuse keeps the link."""
    c = Class(world)
    world.files.refuse = TypeNotAllowedError()

    await importer(world, scripted()).import_materials(
        READER, materials(c.lesson.id)[:1]
    )

    refs = await world.services.public.lesson_resources(c.lesson.id)
    assert [(r.title, r.kind) for r in refs] == [("Classwork: Jadids", "url")]


async def test_a_rerun_downloads_nothing_again(world: LinksWorld) -> None:
    """Idempotent: a (lesson, URL) already imported is skipped before downloading."""
    c = Class(world)
    emis = scripted()
    use_case = importer(world, emis)
    await use_case.import_materials(READER, materials(c.lesson.id))

    again = await use_case.import_materials(READER, materials(c.lesson.id))

    assert again == 0
    assert len(emis.downloads) == 2


async def test_purge_removes_only_emis_materials_and_their_objects(
    world: LinksWorld,
) -> None:
    """The admin re-sync: teacher uploads and their files stay."""
    c = Class(world)
    emis = scripted()
    use_case = importer(world, emis)
    await use_case.import_materials(READER, materials(c.lesson.id))
    own = world.files.add(c.teacher.user_id, name="Notes.pdf")
    await world.services.add_lesson_resources.execute(
        c.teacher,
        c.lesson.id,
        role=LessonRole.MATERIAL,
        kind=LinkKind.FILE,
        file_id=own.id,
    )
    emis_files = set(world.files.objects)

    purged = await use_case.purge([c.lesson.id])

    assert purged == 2
    assert set(world.files.deleted) == emis_files
    assert world.files.objects == {}
    assert own.id in world.files.files
    refs = await world.services.public.lesson_resources(c.lesson.id)
    assert [(r.title, r.source) for r in refs] == [("Notes.pdf", "user")]
    again = await use_case.import_materials(READER, materials(c.lesson.id))
    assert again == 3  # a purge frees the URLs: they are downloaded fresh
