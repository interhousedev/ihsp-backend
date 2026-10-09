"""The demo seed runs twice without duplicates; admin tools work on its data."""

import datetime as dt
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.users import ADMIN_LOGIN
from app.bootstrap.seed_demo import seed
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest
from sqlalchemy import text


async def _admin(container: Container) -> Actor:
    user = await container.identity.directory.user_by_login(ADMIN_LOGIN)
    assert user is not None
    return Actor(user_id=user.id, roles=frozenset({Role.ADMIN, Role.LMS_ADMIN}))


async def _counts(container: Container) -> tuple[int, int, int, int]:
    schedule = container.academic.schedule
    groups = await schedule.list_groups.execute(None)
    entries = await schedule.list_entries.execute(await _admin(container))
    members = await schedule.queries.group_user_ids([g.id for g in groups])
    teachers = await container.identity.directory.user_ids_with_roles([Role.TEACHER])
    return len(groups), len(entries), len(members), len(teachers)


async def test_seed_is_idempotent(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """Running the seed again changes nothing that exists."""
    container = await make_container("all")

    await seed(container, world.credentials)
    first = await _counts(container)
    await seed(container, world.credentials)

    assert first == await _counts(container)
    groups, entries, members, teachers = first
    assert (groups, members, teachers) == (2, 2, 5)
    assert entries > 20


async def test_seed_creates_one_demo_notebook_with_every_output(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """NB-1, NB-8: the demo notebook has three sources, a chat turn and every output."""
    container = await make_container("all")

    await seed(container, world.credentials)
    await seed(container, world.credentials)

    async with container.sessionmaker() as session:
        books = (
            await session.execute(text("SELECT id FROM notebooks.notebooks"))
        ).all()
        sources = await session.scalar(
            text("SELECT count(*) FROM notebooks.sources WHERE status = 'ready'")
        )
        messages = await session.scalar(text("SELECT count(*) FROM notebooks.messages"))
        kinds = (
            (
                await session.execute(
                    text(
                        "SELECT kind FROM notebooks.artifacts WHERE status = 'ready' "
                        "ORDER BY kind"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(books) == 1
    assert (sources, messages) == (3, 2)
    assert list(kinds) == sorted(
        [
            "report",
            "mind_map",
            "flashcards",
            "quiz",
            "data_table",
            "slides",
            "infographic",
        ]
    )


async def test_admin_tools_read_and_write_the_seeded_school(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """AI-6, MCP admin: the adapter maps tool names to use cases for both namings."""
    container = await make_container("all")
    await seed(container, world.credentials)
    admin = await _admin(container)
    tools = container.admin_tools
    today = container.clock.now().date()

    groups = await tools.call("list_groups", {}, admin)
    names = {g["name"] for g in groups["groups"]}
    group_id = next(g["id"] for g in groups["groups"] if g["name"] == "2TN2")
    detail = await tools.call("get_group", {"group_id": group_id}, admin)
    found = await tools.call("search_users", {"query": "usmonov"}, admin)
    teachers = await tools.call("list_teachers", {"limit": 10}, admin)

    assert names == {"2TN2", "1TN1"}
    assert len(detail["students"]) == 1
    assert [u["login"] for u in found["users"]] == ["usmonov.bobur"]
    assert sorted(found["users"][0]["roles"]) == ["lms_creator", "teacher"]
    assert len(teachers["teachers"]) == 5

    for date_args in (
        {"from": today.isoformat(), "to": (today + dt.timedelta(days=6)).isoformat()},
        {
            "date_from": today.isoformat(),
            "date_to": (today + dt.timedelta(days=6)).isoformat(),
        },
    ):
        lessons = await tools.call("list_lessons", date_args, admin)
        assert lessons["lessons"], date_args
    stats = await tools.call(
        "attendance_stats",
        {"date_from": "2026-09-02", "date_to": today.isoformat()},
        admin,
    )
    assert isinstance(stats, dict)
    missing = await tools.call(
        "missing_attendance",
        {"date_from": "2026-09-02", "date_to": today.isoformat()},
        admin,
    )
    assert "lessons" in missing
    assert "runs" in await tools.call("sync_status", {}, admin)
    assert "events" in await tools.call("audit_log", {"limit": 5}, admin)

    created = await tools.call(
        "create_broadcast_draft",
        {
            "title": "From the assistant",
            "text": "Hello",
            "audience": {"everyone": True},
        },
        admin,
    )
    drafts = await tools.call("list_broadcasts", {"status": "draft"}, admin)
    assert created["broadcast"]["created_via"] == "assistant"
    assert len(drafts["items"]) == 2  # the seed's draft and this one


async def test_unknown_tool_is_not_found(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """A tool name outside the catalog is refused."""
    container = await make_container("all")

    with pytest.raises(NotFoundError):
        await container.admin_tools.call(
            "delete_everything", {}, Actor(user_id=UUID(int=1), roles=frozenset())
        )


async def _library_counts(container: Container) -> dict[str, int]:
    async with container.sessionmaker() as session:
        counts = {}
        for name, query in {
            "books": "SELECT count(*) FROM library.items WHERE kind = 'book'",
            "published_books": "SELECT count(*) FROM library.items "
            "WHERE kind = 'book' AND status = 'published'",
            "published_materials": "SELECT count(*) FROM library.items "
            "WHERE kind = 'material' AND status = 'published'",
            "queued_materials": "SELECT count(*) FROM library.items "
            "WHERE kind = 'material' AND status = 'pending_review'",
            "topics": "SELECT count(*) FROM library.topics",
            "collections": "SELECT count(*) FROM library.collections",
            "reading_lists": "SELECT count(*) FROM library.reading_lists "
            "WHERE status = 'published'",
            "librarians": "SELECT count(*) FROM id.users "
            "WHERE 'librarian' = ANY(roles)",
        }.items():
            counts[name] = int(await session.scalar(text(query)) or 0)
    return counts


async def test_seed_adds_the_demo_library_once(
    make_container: ContainerFactory,
    world: IntegrationWorld,
) -> None:
    """Books, topics, a collection, a list, two materials, a librarian; no repeats."""
    container = await make_container("all")

    await seed(container, world.credentials)
    first = await _library_counts(container)
    await seed(container, world.credentials)

    assert first == await _library_counts(container)
    assert first == {
        "books": 6,
        "published_books": 6,
        "published_materials": 1,
        "queued_materials": 1,
        "topics": 2,
        "collections": 1,
        "reading_lists": 1,
        "librarians": 1,
    }


async def test_seed_skips_the_library_when_the_feature_is_off(
    make_container: ContainerFactory,
    world: IntegrationWorld,
    settings: Settings,
) -> None:
    """FEATURES__LIBRARY=false: no library data and no librarian."""
    container = await make_container("all")
    container.settings = settings.model_copy(
        update={"features": settings.features.model_copy(update={"library": False})}
    )

    await seed(container, world.credentials)

    assert (await _library_counts(container))["books"] == 0
    assert (await _library_counts(container))["librarians"] == 0
