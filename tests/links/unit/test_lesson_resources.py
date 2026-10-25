"""ACA-9, UF-WEB-07/08, UF-STF-04/08: lesson materials and attachments."""

from collections.abc import Sequence
from datetime import date, timedelta
from uuid import UUID

from app.modules.links.application.views import ResourceView
from app.modules.links.domain.errors import (
    BlockedUrlError,
    InvalidLinkTargetError,
    LessonMismatchError,
    LessonWindowClosedError,
    LinkNotFoundError,
    ResourceForbiddenError,
)
from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest

TODAY = date(2026, 10, 6)


class Class:
    """A lesson with its teacher, two students and a room."""

    def __init__(self, world: LinksWorld, day: date = TODAY) -> None:
        """Create the people, the room and the lesson."""
        self.teacher = world.person("Galina", Role.TEACHER)
        self.student = world.person("Aleksey")
        self.other = world.person("Madina")
        self.outsider = world.person("Zed")
        self.admin = world.person("Root", Role.ADMIN)
        self.room = world.schedule.add_room("102")
        self.lesson = world.schedule.add_lesson(
            day=day,
            teacher_id=self.teacher.user_id,
            room=self.room,
            students=[self.student.user_id, self.other.user_id],
        )


async def _attach(
    world: LinksWorld,
    actor: Actor,
    lesson_id: UUID,
    role: LessonRole = LessonRole.ATTACHMENT,
    url: str = "https://example.org/derivatives",
    also_lesson_ids: Sequence[UUID] = (),
) -> list[ResourceView]:
    return await world.services.add_lesson_resources.execute(
        actor,
        lesson_id,
        role=role,
        kind=LinkKind.URL,
        target_url=url,
        also_lesson_ids=also_lesson_ids,
    )


async def test_student_in_the_window_attaches_a_link(world: LinksWorld) -> None:
    """UF-WEB-07: a student adds an attachment to a lesson of their audience."""
    c = Class(world)

    views = await _attach(world, c.student, c.lesson.id)

    assert len(views) == 1
    link = views[0].link
    assert link.lesson_id == c.lesson.id
    assert link.lesson_role is LessonRole.ATTACHMENT
    assert link.owner_id == c.student.user_id
    assert views[0].author.first_name == "Aleksey"
    assert views[0].short_url.endswith(link.slug)


async def test_student_adds_a_file_with_its_name_as_the_title(
    world: LinksWorld,
) -> None:
    """UF-WEB-07: files give 8-character IDs and show the file name."""
    c = Class(world)
    file = world.files.add(c.student.user_id, name="Derivatives.pdf")

    views = await world.services.add_lesson_resources.execute(
        c.student,
        c.lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.FILE,
        file_id=file.id,
    )

    assert views[0].title == "Derivatives.pdf"
    assert len(views[0].link.slug) == 8


@pytest.mark.parametrize("offset", [-8, 15])
async def test_student_outside_the_window_is_refused(
    world: LinksWorld, offset: int
) -> None:
    """UF-WEB-07 alternative 1a: more than 7 days ago or 14 days ahead."""
    c = Class(world, TODAY + timedelta(days=offset))

    with pytest.raises(LessonWindowClosedError) as error:
        await _attach(world, c.student, c.lesson.id)

    assert error.value.status == 403


@pytest.mark.parametrize("offset", [-7, 14])
async def test_window_edges_are_inclusive(world: LinksWorld, offset: int) -> None:
    """UF-WEB-07: 7 days back and 14 days ahead still work."""
    c = Class(world, TODAY + timedelta(days=offset))

    assert len(await _attach(world, c.student, c.lesson.id)) == 1


async def test_student_outside_the_audience_is_refused(world: LinksWorld) -> None:
    """UF-WEB-07 alternative 1a: not the student's lesson."""
    c = Class(world)

    with pytest.raises(ResourceForbiddenError):
        await _attach(world, c.outsider, c.lesson.id)


async def test_student_cannot_add_a_material(world: LinksWorld) -> None:
    """ACA-9: materials are for the teacher and Administration."""
    c = Class(world)

    with pytest.raises(ResourceForbiddenError):
        await _attach(world, c.student, c.lesson.id, role=LessonRole.MATERIAL)


@pytest.mark.parametrize("who", ["teacher", "admin"])
async def test_teacher_and_admin_add_materials(world: LinksWorld, who: str) -> None:
    """ACA-9, UF-STF-04: materials by the lesson's teacher or an admin."""
    c = Class(world)

    views = await _attach(world, getattr(c, who), c.lesson.id, role=LessonRole.MATERIAL)

    assert views[0].link.lesson_role is LessonRole.MATERIAL


async def test_teacher_of_another_lesson_is_refused(world: LinksWorld) -> None:
    """ACA-9: only the lesson's own teacher."""
    c = Class(world)
    other_teacher = world.person("Igor", Role.TEACHER)

    with pytest.raises(ResourceForbiddenError):
        await _attach(world, other_teacher, c.lesson.id, role=LessonRole.MATERIAL)


async def test_homework_files_cannot_be_added_here(world: LinksWorld) -> None:
    """Link model: the homework role is reserved for EMIS homework files."""
    c = Class(world)

    with pytest.raises(InvalidLinkTargetError):
        await _attach(world, c.teacher, c.lesson.id, role=LessonRole.HOMEWORK)


async def test_also_add_to_other_lessons_of_the_same_subject_and_day(
    world: LinksWorld,
) -> None:
    """UF-STF-04 step 3: one link per lesson, same target."""
    c = Class(world)
    second = world.schedule.add_lesson(
        period=4,
        subject_id=c.lesson.subject_id,
        teacher_id=c.teacher.user_id,
        group_names=("2TN1",),
    )

    views = await _attach(
        world,
        c.teacher,
        c.lesson.id,
        role=LessonRole.MATERIAL,
        also_lesson_ids=[second.id, second.id, c.lesson.id],
    )

    assert [v.link.lesson_id for v in views] == [c.lesson.id, second.id]
    assert len({v.link.slug for v in views}) == 2
    assert {v.link.target_url for v in views} == {"https://example.org/derivatives"}


async def test_also_add_is_limited_to_teachers_of_those_lessons(
    world: LinksWorld,
) -> None:
    """UF-STF-04: only lessons the teacher teaches, same subject, same date."""
    c = Class(world)
    foreign = world.schedule.add_lesson(
        period=5,
        subject_id=c.lesson.subject_id,
        teacher_id=world.person("Igor", Role.TEACHER).user_id,
    )
    other_subject = world.schedule.add_lesson(period=6, teacher_id=c.teacher.user_id)
    other_day = world.schedule.add_lesson(
        day=TODAY + timedelta(days=1),
        subject_id=c.lesson.subject_id,
        teacher_id=c.teacher.user_id,
    )

    with pytest.raises(ResourceForbiddenError):
        await _attach(world, c.teacher, c.lesson.id, also_lesson_ids=[foreign.id])
    with pytest.raises(LessonMismatchError):
        await _attach(world, c.teacher, c.lesson.id, also_lesson_ids=[other_subject.id])
    with pytest.raises(LessonMismatchError):
        await _attach(world, c.teacher, c.lesson.id, also_lesson_ids=[other_day.id])


async def test_students_and_admins_cannot_use_also_add(world: LinksWorld) -> None:
    """UF-STF-04: the option is for teachers."""
    c = Class(world)
    second = world.schedule.add_lesson(period=4, subject_id=c.lesson.subject_id)

    with pytest.raises(ResourceForbiddenError):
        await _attach(world, c.student, c.lesson.id, also_lesson_ids=[second.id])
    with pytest.raises(ResourceForbiddenError):
        await _attach(world, c.admin, c.lesson.id, also_lesson_ids=[second.id])


async def test_adding_the_same_target_twice_returns_the_existing_link(
    world: LinksWorld,
) -> None:
    """Retries and double clicks do not create duplicates."""
    c = Class(world)

    first = await _attach(world, c.student, c.lesson.id)
    second = await _attach(world, c.student, c.lesson.id)

    assert first[0].link.id == second[0].link.id
    assert len(world.uow.store.links) == 1


async def test_blocked_url_is_refused_for_resources_too(world: LinksWorld) -> None:
    """UF-WEB-07 alternative 2d."""
    c = Class(world)

    with pytest.raises(BlockedUrlError):
        await _attach(world, c.student, c.lesson.id, url="https://blocked.example/x")


async def test_every_change_clears_the_room_page_cache(world: LinksWorld) -> None:
    """ROOM-8: add, hide and delete clear room:{slug}:{date}."""
    c = Class(world)
    key = f"room:{c.room.slug}:{TODAY.isoformat()}"
    await world.redis.set(key, "<html>old</html>")

    views = await _attach(world, c.student, c.lesson.id)
    assert await world.redis.get(key) is None

    await world.redis.set(key, "<html>old</html>")
    await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, views[0].link.id, hidden=True
    )
    assert await world.redis.get(key) is None

    await world.redis.set(key, "<html>old</html>")
    await world.services.delete_lesson_resource.execute(
        c.admin, c.lesson.id, views[0].link.id
    )
    assert await world.redis.get(key) is None


async def test_every_change_asks_the_notebooks_to_sync_the_lesson(
    world: LinksWorld,
) -> None:
    """NB-AUTO: add, hide and delete kick `notebooks.sync_lesson_notebooks`."""
    c = Class(world)
    task = "notebooks.sync_lesson_notebooks"
    expected = (task, {"lesson_id": str(c.lesson.id)})

    views = await _attach(world, c.student, c.lesson.id)
    assert world.kicker.calls == [expected]

    await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, views[0].link.id, hidden=True
    )
    assert world.kicker.calls == [expected, expected]

    await world.services.delete_lesson_resource.execute(
        c.admin, c.lesson.id, views[0].link.id
    )
    assert world.kicker.calls == [expected, expected, expected]


async def test_list_shows_materials_first_and_hides_hidden_from_other_students(
    world: LinksWorld,
) -> None:
    """ACA-9, STF-6, UF-STF-08: hidden attachments are visible to teacher and author."""
    c = Class(world)
    attachment = (await _attach(world, c.student, c.lesson.id))[0]
    await _attach(
        world,
        c.teacher,
        c.lesson.id,
        role=LessonRole.MATERIAL,
        url="https://example.org/m",
    )
    await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, attachment.link.id, hidden=True
    )

    as_teacher = await world.services.list_lesson_resources.execute(
        c.teacher, c.lesson.id
    )
    as_author = await world.services.list_lesson_resources.execute(
        c.student, c.lesson.id
    )
    as_other = await world.services.list_lesson_resources.execute(c.other, c.lesson.id)

    assert [v.link.lesson_role for v in as_teacher] == [
        LessonRole.MATERIAL,
        LessonRole.ATTACHMENT,
    ]
    assert as_teacher[1].link.is_hidden
    assert [v.link.lesson_role for v in as_author] == [
        LessonRole.MATERIAL,
        LessonRole.ATTACHMENT,
    ]
    assert [v.link.lesson_role for v in as_other] == [LessonRole.MATERIAL]


async def test_outsiders_cannot_list_resources(world: LinksWorld) -> None:
    """ACA-9: resources are for the audience, the teacher and Administration."""
    c = Class(world)

    with pytest.raises(ResourceForbiddenError):
        await world.services.list_lesson_resources.execute(c.outsider, c.lesson.id)


async def test_unknown_lesson_is_a_404(world: LinksWorld) -> None:
    """Missing lessons answer 404."""
    c = Class(world)

    with pytest.raises(LinkNotFoundError):
        await world.services.list_lesson_resources.execute(c.student, new_id())


async def test_students_cannot_hide_resources(world: LinksWorld) -> None:
    """STF-6: hiding is for the lesson's teacher and Administration."""
    c = Class(world)
    views = await _attach(world, c.student, c.lesson.id)

    with pytest.raises(ResourceForbiddenError):
        await world.services.hide_lesson_resource.execute(
            c.student, c.lesson.id, views[0].link.id, hidden=True
        )


async def test_hidden_resource_can_be_shown_again(world: LinksWorld) -> None:
    """STF-6: hide is reversible."""
    c = Class(world)
    views = await _attach(world, c.student, c.lesson.id)
    link_id = views[0].link.id

    hidden = await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, link_id, hidden=True
    )
    shown = await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, link_id, hidden=False
    )

    assert hidden.link.hidden_by == c.teacher.user_id
    assert not shown.link.is_hidden


async def test_author_and_admin_delete_resources_but_other_students_cannot(
    world: LinksWorld,
) -> None:
    """UF-WEB-08: the author or an admin deletes; the link then answers 410."""
    c = Class(world)
    mine = (await _attach(world, c.student, c.lesson.id))[0]
    theirs = (await _attach(world, c.other, c.lesson.id, url="https://example.org/2"))[
        0
    ]

    with pytest.raises(ResourceForbiddenError):
        await world.services.delete_lesson_resource.execute(
            c.other, c.lesson.id, mine.link.id
        )
    await world.services.delete_lesson_resource.execute(
        c.student, c.lesson.id, mine.link.id
    )
    await world.services.delete_lesson_resource.execute(
        c.admin, c.lesson.id, theirs.link.id
    )

    assert world.uow.store.links[mine.link.id].revoked_at is not None
    assert world.uow.store.links[theirs.link.id].revoked_at is not None
    assert (
        await world.services.list_lesson_resources.execute(c.teacher, c.lesson.id) == []
    )


async def test_resource_of_another_lesson_is_not_found(world: LinksWorld) -> None:
    """Routes check that the link belongs to the lesson in the path."""
    c = Class(world)
    other = world.schedule.add_lesson(period=4, students=[c.student.user_id])
    mine = (await _attach(world, c.student, c.lesson.id))[0]

    with pytest.raises(LinkNotFoundError):
        await world.services.delete_lesson_resource.execute(
            c.student, other.id, mine.link.id
        )


async def test_public_api_returns_visible_resources_for_other_modules(
    world: LinksWorld,
) -> None:
    """BOT-15, ai tools: LinksApi lists visible resources, materials first."""
    c = Class(world)
    att = (await _attach(world, c.student, c.lesson.id))[0]
    await _attach(
        world,
        c.teacher,
        c.lesson.id,
        role=LessonRole.MATERIAL,
        url="https://example.org/m",
    )
    hidden = (await _attach(world, c.other, c.lesson.id, url="https://example.org/h"))[
        0
    ]
    await world.services.hide_lesson_resource.execute(
        c.teacher, c.lesson.id, hidden.link.id, hidden=True
    )

    visible = await world.services.public.lesson_resources(c.lesson.id)
    everything = await world.services.public.lesson_resources(
        c.lesson.id, include_hidden=True
    )
    grouped = await world.services.public.resources_for_lessons([c.lesson.id])

    assert [r.role for r in visible] == ["material", "attachment"]
    assert visible[1].link_id == att.link.id
    assert visible[1].author_first_name == "Aleksey"
    assert {r.link_id for r in everything} == {
        att.link.id,
        hidden.link.id,
        visible[0].link_id,
    }
    assert grouped == {c.lesson.id: visible}
    assert await world.services.public.resources_for_lessons([]) == {}


async def test_public_api_adds_a_resource(world: LinksWorld) -> None:
    """BOT-17 (UF-BOT-09): the bot adds a resource through the contract."""
    c = Class(world)

    ref = await world.services.public.add_lesson_resource(
        c.teacher, c.lesson.id, role="material", url="https://example.org/bot"
    )

    assert ref.role == "material"
    assert ref.kind == "url"
    assert ref.lesson_id == c.lesson.id


async def test_revoking_an_owner_revokes_their_resources_and_clears_rooms(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ID-28, SHR-7: closing an account removes what the user published."""
    c = Class(world)
    await _attach(world, c.student, c.lesson.id)
    await _attach(world, c.other, c.lesson.id, url="https://example.org/2")
    key = f"room:{c.room.slug}:{TODAY.isoformat()}"
    await world.redis.set(key, "<html>old</html>")

    revoked = await world.services.revoke_owner.execute(c.student.user_id)

    assert revoked == 1
    assert await world.redis.get(key) is None
    live = [x for x in world.uow.store.links.values() if x.revoked_at is None]
    assert [x.owner_id for x in live] == [c.other.user_id]
