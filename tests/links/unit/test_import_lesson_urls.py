"""ACA-9: web addresses EMIS attaches to lessons (author "EMIS")."""

from datetime import date

from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.actor import Role
from app.shared.contracts.links import EMIS_AUTHOR_ID, ImportedUrl
from tests.fakes.links.world import LinksWorld
from tests.links.unit.test_lesson_resources import Class

TOPIC = "https://cdn-emis.edu.uz/files/a.pdf"
VIDEO = "https://www.youtube.com/watch?v=q0sUmfmG7gI"


async def test_urls_become_materials_authored_by_emis(world: LinksWorld) -> None:
    """The students see EMIS as the author and the source "emis" on each resource."""
    c = Class(world)

    added = await world.services.public.import_lesson_urls(
        [
            ImportedUrl(c.lesson.id, TOPIC, "Jadids"),
            ImportedUrl(c.lesson.id, VIDEO, "Jadids (video)"),
        ]
    )

    assert added == 2
    refs = await world.services.public.lesson_resources(c.lesson.id)
    assert [(r.title, r.role, r.kind, r.source) for r in refs] == [
        ("Jadids", "material", "url", "emis"),
        ("Jadids (video)", "material", "url", "emis"),
    ]
    assert {(r.author_id, r.author_first_name) for r in refs} == {
        (EMIS_AUTHOR_ID, "EMIS")
    }
    assert world.titles.urls == []  # EMIS gives the title; no page is fetched


async def test_importing_the_same_url_again_adds_nothing(world: LinksWorld) -> None:
    """The daily re-sync is idempotent."""
    c = Class(world)
    item = ImportedUrl(c.lesson.id, TOPIC, "Jadids")
    await world.services.public.import_lesson_urls([item])

    again = await world.services.public.import_lesson_urls([item, item])

    assert again == 0
    assert len(await world.services.public.lesson_resources(c.lesson.id)) == 1


async def test_a_resource_a_teacher_deleted_is_not_brought_back(
    world: LinksWorld,
) -> None:
    """A teacher's decision to drop an EMIS file outlasts the next sync."""
    c = Class(world)
    await world.services.public.import_lesson_urls(
        [ImportedUrl(c.lesson.id, TOPIC, "Jadids")]
    )
    [ref] = await world.services.public.lesson_resources(c.lesson.id)
    await world.services.delete_lesson_resource.execute(
        c.teacher, c.lesson.id, ref.link_id
    )

    again = await world.services.public.import_lesson_urls(
        [ImportedUrl(c.lesson.id, TOPIC, "Jadids")]
    )

    assert again == 0
    assert await world.services.public.lesson_resources(c.lesson.id) == []


async def test_the_same_url_on_another_lesson_is_a_new_resource(
    world: LinksWorld,
) -> None:
    """Deduplication is per lesson."""
    c = Class(world)
    other = world.schedule.add_lesson(
        day=date(2026, 10, 7),
        teacher_id=c.teacher.user_id,
        room=c.room,
        students=[c.student.user_id],
    )

    added = await world.services.public.import_lesson_urls(
        [ImportedUrl(c.lesson.id, TOPIC, "A"), ImportedUrl(other.id, TOPIC, "B")]
    )

    assert added == 2


async def test_unsafe_urls_are_skipped_and_the_others_still_attach(
    world: LinksWorld,
) -> None:
    """A bad address from EMIS must not stop the good ones."""
    c = Class(world)

    added = await world.services.public.import_lesson_urls(
        [
            ImportedUrl(c.lesson.id, "javascript:alert(1)", "bad"),
            ImportedUrl(c.lesson.id, "https://user:pw@example.org/x", "bad"),
            ImportedUrl(c.lesson.id, "not a url", "bad"),
            ImportedUrl(c.lesson.id, TOPIC, "good"),
        ]
    )

    assert added == 1
    [ref] = await world.services.public.lesson_resources(c.lesson.id)
    assert ref.title == "good"


async def test_no_rate_limit_applies_to_a_whole_group_import(world: LinksWorld) -> None:
    """No user acts, so the per-user link creation limit does not."""
    c = Class(world)
    urls = [
        ImportedUrl(c.lesson.id, f"https://cdn-emis.edu.uz/files/{n}.pdf", f"f{n}")
        for n in range(60)
    ]

    assert await world.services.public.import_lesson_urls(urls) == 60


async def test_a_teacher_can_still_hide_an_emis_resource(world: LinksWorld) -> None:
    """Teachers manage EMIS resources like any other; the author stays EMIS."""
    c = Class(world)
    await world.services.public.import_lesson_urls(
        [ImportedUrl(c.lesson.id, TOPIC, "Jadids")]
    )
    [ref] = await world.services.public.lesson_resources(c.lesson.id)

    await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, ref.link_id, hidden=True
    )

    assert await world.services.public.lesson_resources(c.lesson.id) == []
    [hidden] = await world.services.public.lesson_resources(
        c.lesson.id, include_hidden=True
    )
    assert hidden.hidden and hidden.source == "emis"


async def test_people_resources_are_labelled_as_users(world: LinksWorld) -> None:
    """Only EMIS imports are labelled "emis"."""
    c = Class(world)
    await world.services.add_lesson_resources.execute(
        c.teacher,
        c.lesson.id,
        role=LessonRole.MATERIAL,
        kind=LinkKind.URL,
        target_url="https://example.org/derivatives",
    )

    [ref] = await world.services.public.lesson_resources(c.lesson.id)

    assert ref.source == "user" and ref.author_id == c.teacher.user_id
    assert Role.TEACHER in c.teacher.roles


async def test_only_the_lessons_teacher_and_admins_may_delete_an_emis_resource(
    world: LinksWorld,
) -> None:
    """A student cannot remove what EMIS brought; the teacher and an admin can."""
    from app.modules.links.domain.errors import ResourceForbiddenError

    import pytest

    c = Class(world)
    await world.services.public.import_lesson_urls(
        [
            ImportedUrl(c.lesson.id, TOPIC, "a"),
            ImportedUrl(c.lesson.id, VIDEO, "b"),
        ]
    )
    first, second = await world.services.public.lesson_resources(c.lesson.id)

    with pytest.raises(ResourceForbiddenError):
        await world.services.delete_lesson_resource.execute(
            c.student, c.lesson.id, first.link_id
        )
    stranger = world.person("Stranger", Role.TEACHER)
    with pytest.raises(ResourceForbiddenError):
        await world.services.delete_lesson_resource.execute(
            stranger, c.lesson.id, first.link_id
        )
    await world.services.delete_lesson_resource.execute(
        c.teacher, c.lesson.id, first.link_id
    )
    await world.services.delete_lesson_resource.execute(
        c.admin, c.lesson.id, second.link_id
    )

    assert await world.services.public.lesson_resources(c.lesson.id) == []
