"""Lesson sources of a subject by group, and the "hide EMIS sources" group rule."""

from datetime import date
from typing import Any
from uuid import UUID

from app.modules.links.application.lesson_sources import LessonSourcePage
from app.modules.links.domain.errors import NotTeachingSubjectError
from app.modules.links.domain.link import Link
from app.shared.actor import Role
from app.shared.contracts.links import EMIS_AUTHOR_ID, ImportedUrl
from app.shared.ids import new_id
from tests.fakes.links.world import LinksWorld

import pytest

SUBJECT = new_id()
G1, G2 = new_id(), new_id()


class Setup:
    """A teacher with two lessons for group 1A and one for 1B, plus another teacher."""

    def __init__(self, world: LinksWorld) -> None:
        """Create the people and lessons."""
        self.world = world
        self.teacher = world.person("Galina", Role.TEACHER)
        self.other = world.person("Oleg", Role.TEACHER)
        add = world.schedule.add_lesson
        tid = self.teacher.user_id
        self.a_old = add(
            day=date(2026, 10, 5),
            subject_id=SUBJECT,
            teacher_id=tid,
            groups=[(G1, "1A")],
        )
        self.a_new = add(
            day=date(2026, 10, 7),
            subject_id=SUBJECT,
            teacher_id=tid,
            groups=[(G1, "1A")],
        )
        self.b = add(
            day=date(2026, 10, 6),
            subject_id=SUBJECT,
            teacher_id=tid,
            groups=[(G2, "1B")],
        )
        self.foreign = add(
            day=date(2026, 10, 6),
            subject_id=SUBJECT,
            teacher_id=self.other.user_id,
            groups=[(G1, "1A")],
        )

    async def emis(self, lesson_id: UUID, url: str, title: str) -> None:
        """Import one EMIS URL."""
        await self.world.services.public.import_lesson_urls(
            [ImportedUrl(lesson_id, url, title)]
        )

    def links(self, lesson_id: UUID) -> list[Link]:
        """Committed links of a lesson."""
        return [
            x for x in self.world.uow.store.links.values() if x.lesson_id == lesson_id
        ]


async def _list(
    world: LinksWorld, teacher_id: UUID | None, **kw: Any
) -> LessonSourcePage:
    params: dict[str, Any] = {
        "group_id": None,
        "origin": "emis",
        "limit": 50,
        "offset": 0,
    }
    params.update(kw)
    return await world.services.list_lesson_sources.execute(
        SUBJECT, teacher_id=teacher_id, **params
    )


async def test_listing_groups_then_newest_and_scopes_teacher(world: LinksWorld) -> None:
    """Group 1A first, newest lesson first; a teacher sees only their lessons."""
    s = Setup(world)
    await s.emis(s.a_old.id, "https://e.uz/old", "Old")
    await s.emis(s.a_new.id, "https://e.uz/new", "New")
    await s.emis(s.b.id, "https://e.uz/b", "Bee")
    await s.emis(s.foreign.id, "https://e.uz/f", "Foreign")

    mine = await _list(world, s.teacher.user_id)
    assert [(i.group_name, i.title) for i in mine.items] == [
        ("1A", "07.10 New"),
        ("1A", "05.10 Old"),
        ("1B", "06.10 Bee"),
    ]
    assert mine.total == 3
    admin = await _list(world, None)
    assert admin.total == 4
    page = await _list(world, s.teacher.user_id, group_id=G1, limit=1, offset=1)
    assert [i.title for i in page.items] == ["05.10 Old"] and page.total == 2


async def test_origin_emis_skips_teacher_materials(world: LinksWorld) -> None:
    """origin=emis keeps EMIS ones only; origin=all includes the teacher's own."""
    s = Setup(world)
    await s.emis(s.b.id, "https://e.uz/b", "Bee")
    [link] = s.links(s.b.id)
    own = Link(
        id=new_id(),
        slug="own1",
        kind=link.kind,
        owner_id=s.teacher.user_id,
        created_at=link.created_at,
        target_url="https://own.example/x",
        title="Own",
        lesson_id=s.b.id,
        lesson_role=link.lesson_role,
    )
    world.uow.store.links[own.id] = own
    world.identity.add("Galina", "G")

    assert (await _list(world, s.teacher.user_id)).total == 1
    assert (await _list(world, s.teacher.user_id, origin="all")).total == 2


async def test_teacher_without_lessons_is_refused(world: LinksWorld) -> None:
    """403 for a subject or group the teacher does not teach."""
    s = Setup(world)
    stranger = world.person("Zed", Role.TEACHER)
    with pytest.raises(NotTeachingSubjectError):
        await _list(world, stranger.user_id)
    with pytest.raises(NotTeachingSubjectError):
        await _list(world, s.other.user_id, group_id=G2)
    with pytest.raises(NotTeachingSubjectError):
        await world.services.emis_sources_hiding.set(
            s.other.user_id, SUBJECT, G2, hidden=True
        )


async def test_toggle_hides_and_unhides_preserving_manual_hides(
    world: LinksWorld,
) -> None:
    """ON hides the group's EMIS sources; OFF shows only those the rule hid."""
    s = Setup(world)
    await s.emis(s.a_old.id, "https://e.uz/old", "Old")
    await s.emis(s.a_new.id, "https://e.uz/new", "New")
    await s.emis(s.b.id, "https://e.uz/b", "Bee")
    await s.emis(s.foreign.id, "https://e.uz/f", "Foreign")
    [manual] = s.links(s.a_old.id)
    await world.services.hide_lesson_resource.execute(
        s.teacher, s.a_old.id, manual.id, hidden=True
    )
    hiding = world.services.emis_sources_hiding

    on = await hiding.set(s.teacher.user_id, SUBJECT, G1, hidden=True)

    assert on.hidden and on.affected == 1  # only a_new: a_old was already hidden
    assert s.links(s.a_new.id)[0].hidden_by_rule
    assert not s.links(s.b.id)[0].is_hidden  # other group
    assert not s.links(s.foreign.id)[0].is_hidden  # other teacher
    assert (await hiding.get(s.teacher.user_id, SUBJECT, G1)).hidden

    off = await hiding.set(s.teacher.user_id, SUBJECT, G1, hidden=False)

    assert not off.hidden and off.affected == 1
    assert not s.links(s.a_new.id)[0].is_hidden
    assert s.links(s.a_old.id)[0].is_hidden  # the manual hide stays
    assert not (await hiding.get(s.teacher.user_id, SUBJECT, G1)).hidden


async def test_import_respects_the_rule(world: LinksWorld) -> None:
    """New EMIS materials of a covered lesson arrive hidden; others visible."""
    s = Setup(world)
    await world.services.emis_sources_hiding.set(
        s.teacher.user_id, SUBJECT, G1, hidden=True
    )

    await s.emis(s.a_new.id, "https://e.uz/new", "New")
    await s.emis(s.b.id, "https://e.uz/b", "Bee")

    [new] = s.links(s.a_new.id)
    assert new.is_hidden and new.hidden_by_rule and new.owner_id == EMIS_AUTHOR_ID
    assert new.hidden_by == s.teacher.user_id
    assert not s.links(s.b.id)[0].is_hidden
    students = await world.services.public.lesson_resources(s.a_new.id)
    assert students == []
