"""Real-database smoke of the activities repositories and the catalog adapter."""

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.activities.domain.club import Club, ClubCapability, ClubKind
from app.modules.activities.domain.course_link import ClubCourseLink
from app.modules.activities.domain.membership import (
    MemberRole,
    Membership,
    MemberStatus,
)
from app.modules.activities.domain.points import PointEntry
from app.modules.activities.infrastructure.catalog import SqlOpportunityCatalog
from app.modules.activities.infrastructure.repositories.sql import (
    SqlClubRepository,
    SqlCourseLinkRepository,
    SqlMembershipRepository,
    SqlPointsRepository,
)
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.ids import new_id

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)


async def test_club_roundtrip_with_capabilities_and_one_owner(
    db_session: AsyncSession,
) -> None:
    clubs, members = SqlClubRepository(db_session), SqlMembershipRepository(db_session)
    club = Club(
        new_id(), "iht-volunteers", ClubKind.CLUB, {"en": "IHT Volunteers"}, new_id()
    )
    club.set_capabilities({ClubCapability.DRAFTING, ClubCapability.POINTS}, by_su=True)
    await clubs.add(club)
    got = await clubs.get_by_slug("iht-volunteers")
    assert got is not None and got.capabilities == club.capabilities
    assert ClubCapability.FORMS in got.capabilities

    owner = Membership(
        club.id, new_id(), MemberRole.OWNER, MemberStatus.ACTIVE, 1, NOW, None
    )
    await members.save(owner)
    owner.status = MemberStatus.LEFT
    await members.save(owner)
    assert (await members.get(club.id, owner.user_id)).status is MemberStatus.LEFT
    await members.save(
        Membership(
            club.id, new_id(), MemberRole.OWNER, MemberStatus.ACTIVE, 1, NOW, None
        )
    )
    with pytest.raises(IntegrityError):
        await members.save(
            Membership(
                club.id, new_id(), MemberRole.OWNER, MemberStatus.ACTIVE, 1, NOW, None
            )
        )


async def test_points_dedupe_and_totals(db_session: AsyncSession) -> None:
    points = SqlPointsRepository(db_session)
    club_id, user, source = new_id(), new_id(), new_id()
    entry = PointEntry(user, "event", source, "attended", 2, NOW, club_id)
    assert await points.add(entry) is True
    assert await points.add(entry) is False
    assert await points.totals(club_id, None, None) == {user: 2}


async def test_course_link_relink_after_end(db_session: AsyncSession) -> None:
    links = SqlCourseLinkRepository(db_session)
    club_id, course_id, who = new_id(), new_id(), new_id()
    first = ClubCourseLink(club_id, course_id, who, "club", "pending", NOW)
    await links.add(first)
    first.status = "ended"
    await links.save(first)
    assert await links.list_for_club(club_id) == []
    await links.add(ClubCourseLink(club_id, course_id, who, "course", "pending", NOW))
    (open_link,) = await links.list_for_club(club_id)
    assert open_link.requested_side == "course"


async def test_catalog_audience_lock_version_and_delete(
    db_session: AsyncSession,
) -> None:
    catalog = SqlOpportunityCatalog(db_session)
    by = uuid4()
    draft = OpportunityDraft(
        kind="event", title="Hackathon", url="https://example.org/h"
    )
    oid = await catalog.apply(draft, frozenset({"admission"}), target_id=None, by=by)
    first = await catalog.get(oid)
    assert first is not None and first.audience == {"admission"}
    await catalog.apply(draft, frozenset({"admission", "my_iht"}), target_id=oid, by=by)
    second = await catalog.get(oid)
    assert second.lock_version == first.lock_version + 1
    assert second.audience == {"admission", "my_iht"}
    assert await catalog.in_use(oid) is False
    await catalog.delete(oid)
    assert await catalog.get(oid) is None


async def test_media_quota_lock_reads_club_usage(db_session: AsyncSession) -> None:
    from app.modules.activities.infrastructure.repositories.media_sql import (
        SqlMediaRepository,
    )

    club = Club(
        new_id(), f"quota-{uuid4().hex[:8]}", ClubKind.CLUB, {"en": "Q"}, new_id()
    )
    await SqlClubRepository(db_session).add(club)
    media = SqlMediaRepository(db_session)
    assert await media.used_bytes_locked(club.id) == 0
    assert await media.used_bytes_locked(new_id()) == 0
