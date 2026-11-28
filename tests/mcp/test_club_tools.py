"""Student club tools over the real activities services with in-memory ports."""

import base64
import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from app.shared.actor import Actor, Role
from tests.fakes.activities.world import ActivitiesWorld, build_world
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, registered_tools, text_of

import pytest

READ = {
    "list_my_clubs",
    "list_club_events",
    "get_club_event",
    "list_club_announcements",
    "list_event_media",
}
WRITE = {
    "create_club_event",
    "update_club_event",
    "publish_club_event",
    "upload_club_media",
    "set_event_cover",
    "add_event_media",
    "send_club_announcement",
    "cancel_club_event",
    "cancel_club_announcement",
    "delete_club_media",
}


def _sha(n: int) -> str:
    return base64.b64encode(hashlib.sha256(str(n).encode()).digest()).decode()


@pytest.fixture
def clubs(world: World, monkeypatch: pytest.MonkeyPatch) -> ActivitiesWorld:
    act = build_world()
    original = world.deps

    def deps(**kwargs: Any) -> Any:  # noqa: ANN401
        return dataclasses.replace(original(**kwargs), activities=act.services)

    monkeypatch.setattr(world, "deps", deps)
    return act


async def _club(act: ActivitiesWorld, owner: Actor, slug: str) -> Any:  # noqa: ANN401
    su = act.add_staff(Role.SU)
    c = await act.services.clubs.create(
        owner, name=slug.title(), slug=slug, description="d"
    )
    await act.services.clubs.submit(owner, c.id)
    await act.services.clubs.review(su, c.id, approve=True, reason=None)
    await act.services.media.set_club_limits(su, c.id, quota_bytes=100_000)
    return c


async def _photo(act: ActivitiesWorld, actor: Actor, club_id: Any, n: int) -> Any:
    svc = act.services.media
    started = await svc.request_upload(
        actor,
        club_id,
        name=f"p{n}.jpg",
        size=400,
        content_type="image/jpeg",
        sha256_b64=_sha(n),
        consent_attested=True,
    )
    await svc.complete(actor, started.media.id)
    await svc.process(started.media.id)
    return started.media.id


def _when(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


async def test_tools_registered_with_hints(
    world: World, clubs: ActivitiesWorld
) -> None:
    """Every catalog tool exists; reads are read-only, writes are not."""
    tools = {t.name: t for t in await registered_tools(world.deps(), "student")}
    assert READ | WRITE <= set(tools)
    for name in READ:
        assert tools[name].annotations.readOnlyHint  # type: ignore[union-attr]
    for name in WRITE:
        assert not tools[name].annotations.readOnlyHint  # type: ignore[union-attr]


async def test_organizer_runs_event_with_cover_and_announcement(
    world: World, clubs: ActivitiesWorld
) -> None:
    """Create, update, cover, album and announcement with a photo."""
    owner = clubs.add_student()
    club = await _club(clubs, owner, "chess")
    token, _ = world.connector_token(
        "student", "clubs:read", "clubs:write", user_id=owner.user_id
    )
    cover = await _photo(clubs, owner, club.id, 1)
    shot = await _photo(clubs, owner, club.id, 2)
    news = await _photo(clubs, owner, club.id, 3)
    async with world.session("student", token) as session:
        mine = data_of(await call(session, "list_my_clubs"))
        assert [c["club_id"] for c in mine["clubs"]] == [str(club.id)]
        event = data_of(
            await call(
                session,
                "create_club_event",
                club_id=str(club.id),
                title="Blitz",
                starts_at=_when(3),
                ends_at=_when(4),
            )
        )["event"]
        eid = event["event_id"]
        read = data_of(await call(session, "get_club_event", event_id=eid))
        for field in ("event.title", "event.title.ru", "event.description.uz"):
            assert field in read["untrusted_fields"]
        assert "clubs[].name.en" in mine["untrusted_fields"]
        updated = data_of(
            await call(session, "update_club_event", event_id=eid, location="Hall")
        )["event"]
        assert updated["location"] == "Hall"
        covered = data_of(
            await call(session, "set_event_cover", event_id=eid, media_id=str(cover))
        )["event"]
        assert covered["cover_media_id"] == str(cover)
        data_of(
            await call(session, "add_event_media", event_id=eid, media_id=str(shot))
        )
        page = data_of(await call(session, "list_event_media", event_id=eid))
        assert [i["media_id"] for i in page["items"]] == [str(shot)]
        sent = data_of(
            await call(
                session,
                "send_club_announcement",
                club_id=str(club.id),
                text="Blitz on Friday",
                media_ids=[str(news)],
            )
        )["announcement"]
        assert sent["sent_at"] is not None
        listed = data_of(
            await call(session, "list_club_announcements", club_id=str(club.id))
        )
        assert listed["announcements"][0]["text"] == "Blitz on Friday"
        assert "announcements[].text" in listed["untrusted_fields"]


async def test_upload_two_steps(world: World, clubs: ActivitiesWorld) -> None:
    """Step 1 returns a presigned PUT; step 2 completes the item."""
    owner = clubs.add_student()
    club = await _club(clubs, owner, "art")
    token, _ = world.connector_token("student", "clubs:write", user_id=owner.user_id)
    async with world.session("student", token) as session:
        started = data_of(
            await call(
                session,
                "upload_club_media",
                club_id=str(club.id),
                name="a.jpg",
                size=400,
                content_type="image/jpeg",
                sha256_b64=_sha(7),
                consent_attested=True,
            )
        )
        assert started["upload_url"] and started["media_id"]
        done = data_of(
            await call(
                session,
                "upload_club_media",
                club_id=str(club.id),
                media_id=started["media_id"],
            )
        )
        assert done["media"]["media_id"] == started["media_id"]
        missing = await call(session, "upload_club_media", club_id=str(club.id))
        assert missing.isError


async def test_non_organizer_refused(world: World, clubs: ActivitiesWorld) -> None:
    """A student who does not organize the club cannot create events or upload."""
    owner = clubs.add_student()
    club = await _club(clubs, owner, "debate")
    stranger = clubs.add_student()
    token, _ = world.connector_token("student", "clubs:write", user_id=stranger.user_id)
    async with world.session("student", token) as session:
        created = await call(
            session,
            "create_club_event",
            club_id=str(club.id),
            title="X",
            starts_at=_when(1),
            ends_at=_when(2),
        )
        upload = await call(
            session,
            "upload_club_media",
            club_id=str(club.id),
            name="a.jpg",
            size=10,
            content_type="image/jpeg",
            sha256_b64=_sha(1),
            consent_attested=True,
        )
        announce = await call(
            session, "send_club_announcement", club_id=str(club.id), text="hi"
        )
    for result in (created, upload, announce):
        assert result.isError
        assert "internal" not in text_of(result).lower()
    assert await clubs.services.events.list_for_club(owner, club.id) == []


async def test_other_club_media_not_found(world: World, clubs: ActivitiesWorld) -> None:
    """An organizer cannot use or delete media of another club."""
    owner = clubs.add_student()
    other_owner = clubs.add_student()
    club = await _club(clubs, owner, "robots")
    other = await _club(clubs, other_owner, "music")
    foreign = await _photo(clubs, other_owner, other.id, 9)
    event = await clubs.services.events.create(
        owner,
        club.id,
        "Demo",
        datetime.now(UTC) + timedelta(days=1),
        datetime.now(UTC) + timedelta(days=2),
    )
    token, _ = world.connector_token("student", "clubs:write", user_id=owner.user_id)
    async with world.session("student", token) as session:
        results = [
            await call(
                session,
                "set_event_cover",
                event_id=str(event.id),
                media_id=str(foreign),
            ),
            await call(
                session,
                "add_event_media",
                event_id=str(event.id),
                media_id=str(foreign),
            ),
            await call(session, "delete_club_media", media_id=str(foreign)),
            await call(
                session,
                "send_club_announcement",
                club_id=str(club.id),
                text="x",
                media_ids=[str(foreign)],
            ),
        ]
    for result in results:
        assert result.isError
        assert "internal" not in text_of(result).lower()
    media = (await clubs.services.media.get(other_owner, foreign)).media
    assert media.deleted_at is None and media.event_id is None


async def test_scope_missing_refused(world: World, clubs: ActivitiesWorld) -> None:
    """clubs:read does not allow writes; no scope allows nothing."""
    owner = clubs.add_student()
    club = await _club(clubs, owner, "film")
    read_token, _ = world.connector_token(
        "student", "clubs:read", user_id=owner.user_id
    )
    none_token, _ = world.connector_token(
        "student", "marks:read", user_id=owner.user_id
    )
    async with world.session("student", read_token) as session:
        write = await call(
            session,
            "create_club_event",
            club_id=str(club.id),
            title="X",
            starts_at=_when(1),
            ends_at=_when(2),
        )
    async with world.session("student", none_token) as session:
        read = await call(session, "list_my_clubs")
    for result in (write, read):
        assert result.isError
        assert "insufficient_scope" in text_of(result)
    assert await clubs.services.events.list_for_club(owner, club.id) == []
