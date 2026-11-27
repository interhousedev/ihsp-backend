"""SQL repositories of the activities module (one class per port)."""

from __future__ import annotations

import builtins
from dataclasses import fields
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

from app.modules.activities.domain.announcement import Announcement
from app.modules.activities.domain.club import (
    Club,
    ClubCapability,
    ClubKind,
    ClubStatus,
    Declaration,
    JoinPolicy,
)
from app.modules.activities.domain.course_link import ClubCourseLink
from app.modules.activities.domain.draft import (
    ClubProfile,
    DraftPick,
    DraftRound,
    DraftSignup,
)
from app.modules.activities.domain.event import Event, EventStatus, Rsvp, RsvpPolicy
from app.modules.activities.domain.membership import (
    MemberRole,
    Membership,
    MemberStatus,
)
from app.modules.activities.domain.ownership import OwnershipTransfer, TransferStatus
from app.modules.activities.domain.planner import PlannerItem, PlannerStatus
from app.modules.activities.domain.points import PointEntry
from app.modules.activities.domain.rating import Rating
from app.modules.activities.domain.report import EventReport
from app.modules.activities.domain.team import (
    ConsentEvent,
    PositionApplication,
    TeamPosition,
    TeamSeat,
)
from app.modules.activities.infrastructure.orm import tables as t
from app.shared.ids import new_id

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")
_OPEN_LINK = ("pending", "active")


def _load(cls: type[T], row: Any, **conv: Any) -> T:
    """Build a dataclass from the same-named row columns; `conv` converts by field."""
    data = {f.name: getattr(row, f.name) for f in fields(cls)}  # type: ignore[arg-type]
    for name, fn in conv.items():
        data[name] = fn(data[name])
    return cls(**data)


def _dump(row_cls: Any, obj: Any, **extra: Any) -> Any:
    """Build a row from the same-named dataclass fields; enums become their values."""
    columns = {a.key for a in row_cls.__mapper__.column_attrs}
    data: dict[str, Any] = {}
    for f in fields(obj):
        if f.name not in columns:
            continue
        value = getattr(obj, f.name)
        data[f.name] = value.value if isinstance(value, Enum) else value
    data.update(extra)
    return row_cls(**data)


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def _upsert(self, row: Any) -> None:
        await self._s.merge(row)
        await self._s.flush()


def _club(r: t.ClubRow) -> Club:
    return _load(
        Club,
        r,
        kind=ClubKind,
        status=ClubStatus,
        join_policy=JoinPolicy,
        capabilities=lambda v: frozenset(ClubCapability(x) for x in v),
    )


class SqlClubRepository(_Repo):
    """Clubs and declarations."""

    async def add(self, club: Club) -> None:
        """Insert a club."""
        await self.save(club)

    async def save(self, club: Club) -> None:
        """Insert or update."""
        await self._upsert(
            _dump(
                t.ClubRow, club, capabilities=sorted(c.value for c in club.capabilities)
            )
        )

    async def get(self, club_id: UUID) -> Club | None:
        """One club."""
        row = await self._s.get(t.ClubRow, club_id)
        return _club(row) if row else None

    async def get_by_slug(self, slug: str) -> Club | None:
        """One club by slug."""
        row = await self._s.scalar(select(t.ClubRow).where(t.ClubRow.slug == slug))
        return _club(row) if row else None

    async def list_all(self) -> list[Club]:
        """Every club."""
        rows = await self._s.scalars(select(t.ClubRow).order_by(t.ClubRow.created_at))
        return [_club(r) for r in rows]

    async def add_declaration(self, declaration: Declaration) -> None:
        """Store a new declaration version."""
        await self._upsert(_dump(t.DeclarationRow, declaration))

    async def latest_declaration(self, club_id: UUID) -> Declaration | None:
        """The newest declaration."""
        row = await self._s.scalar(
            select(t.DeclarationRow)
            .where(t.DeclarationRow.club_id == club_id)
            .order_by(t.DeclarationRow.version.desc())
            .limit(1)
        )
        return _load(Declaration, row) if row else None


def _member(r: t.MembershipRow) -> Membership:
    return _load(Membership, r, role=MemberRole, status=MemberStatus)


class SqlMembershipRepository(_Repo):
    """Memberships."""

    async def get(self, club_id: UUID, user_id: UUID) -> Membership | None:
        """One membership."""
        row = await self._s.get(t.MembershipRow, (club_id, user_id))
        return _member(row) if row else None

    async def save(self, membership: Membership) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.MembershipRow, membership))

    async def list(self, club_id: UUID) -> builtins.list[Membership]:
        """All memberships of a club."""
        rows = await self._s.scalars(
            select(t.MembershipRow).where(t.MembershipRow.club_id == club_id)
        )
        return [_member(r) for r in rows]

    async def list_for_user(self, user_id: UUID) -> builtins.list[Membership]:
        """All memberships of a person."""
        rows = await self._s.scalars(
            select(t.MembershipRow).where(t.MembershipRow.user_id == user_id)
        )
        return [_member(r) for r in rows]


def _transfer(r: t.TransferRow) -> OwnershipTransfer:
    return _load(OwnershipTransfer, r, status=TransferStatus)


class SqlTransferRepository(_Repo):
    """Ownership transfers."""

    async def add(self, transfer: OwnershipTransfer) -> None:
        """Insert."""
        await self.save(transfer)

    async def get(self, transfer_id: UUID) -> OwnershipTransfer | None:
        """One transfer."""
        row = await self._s.get(t.TransferRow, transfer_id)
        return _transfer(row) if row else None

    async def save(self, transfer: OwnershipTransfer) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.TransferRow, transfer))

    async def list_offered(
        self, club_id: UUID | None = None
    ) -> list[OwnershipTransfer]:
        """Open offers, optionally of one club."""
        q = select(t.TransferRow).where(t.TransferRow.status == "offered")
        if club_id is not None:
            q = q.where(t.TransferRow.club_id == club_id)
        return [_transfer(r) for r in await self._s.scalars(q)]


def _event(r: t.EventRow) -> Event:
    return _load(Event, r, status=EventStatus, rsvp_policy=RsvpPolicy)


class SqlEventRepository(_Repo):
    """Events, RSVPs and reports."""

    async def add(self, event: Event) -> None:
        """Insert an event."""
        await self.save(event)

    async def get(self, event_id: UUID) -> Event | None:
        """One event."""
        row = await self._s.get(t.EventRow, event_id)
        return _event(row) if row else None

    async def save(self, event: Event) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.EventRow, event))

    async def list_for_club(self, club_id: UUID) -> list[Event]:
        """Events of a club."""
        rows = await self._s.scalars(
            select(t.EventRow)
            .where(t.EventRow.club_id == club_id)
            .order_by(t.EventRow.starts_at)
        )
        return [_event(r) for r in rows]

    async def list_all(self) -> list[Event]:
        """Every event."""
        rows = await self._s.scalars(select(t.EventRow).order_by(t.EventRow.starts_at))
        return [_event(r) for r in rows]

    async def references_opportunity(self, opportunity_id: UUID) -> bool:
        """Whether an event points at the catalog entry."""
        hit = await self._s.scalar(
            select(t.EventRow.id)
            .where(t.EventRow.opportunity_id == opportunity_id)
            .limit(1)
        )
        return hit is not None

    async def get_rsvp(self, event_id: UUID, user_id: UUID) -> Rsvp | None:
        """One RSVP."""
        row = await self._s.scalar(
            select(t.RsvpRow).where(
                t.RsvpRow.event_id == event_id, t.RsvpRow.user_id == user_id
            )
        )
        return _load(Rsvp, row) if row else None

    async def save_rsvp(self, rsvp: Rsvp) -> None:
        """Insert or update an RSVP."""
        await self._upsert(_dump(t.RsvpRow, rsvp))

    async def list_rsvps(self, event_id: UUID) -> list[Rsvp]:
        """List the RSVPs of an event, oldest first."""
        rows = await self._s.scalars(
            select(t.RsvpRow)
            .where(t.RsvpRow.event_id == event_id)
            .order_by(t.RsvpRow.created_at)
        )
        return [_load(Rsvp, r) for r in rows]

    async def get_report(self, event_id: UUID) -> EventReport | None:
        """The event report."""
        row = await self._s.get(t.EventReportRow, event_id)
        if row is None:
            return None
        return _load(EventReport, row, media_file_ids=lambda v: [UUID(x) for x in v])

    async def save_report(self, report: EventReport) -> None:
        """Insert or update the report."""
        await self._upsert(
            _dump(
                t.EventReportRow,
                report,
                media_file_ids=[str(x) for x in report.media_file_ids],
            )
        )


class SqlRatingRepository(_Repo):
    """Ratings."""

    async def add(self, rating: Rating) -> None:
        """Insert."""
        await self._upsert(_dump(t.RatingRow, rating))

    async def get(self, rating_id: UUID) -> Rating | None:
        """One rating."""
        row = await self._s.get(t.RatingRow, rating_id)
        return _load(Rating, row) if row else None

    async def list_for(self, target_type: str, target_id: UUID) -> list[Rating]:
        """Ratings of one target."""
        rows = await self._s.scalars(
            select(t.RatingRow)
            .where(
                t.RatingRow.target_type == target_type,
                t.RatingRow.target_id == target_id,
            )
            .order_by(t.RatingRow.created_at)
        )
        return [_load(Rating, r) for r in rows]


class SqlAnnouncementRepository(_Repo):
    """Announcements."""

    async def add(self, announcement: Announcement) -> None:
        """Insert."""
        await self.save(announcement)

    async def get(self, announcement_id: UUID) -> Announcement | None:
        """One announcement."""
        row = await self._s.get(t.AnnouncementRow, announcement_id)
        return _load(Announcement, row) if row else None

    async def save(self, announcement: Announcement) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.AnnouncementRow, announcement))

    async def list(self, club_id: UUID) -> builtins.list[Announcement]:
        """Announcements of a club, newest first."""
        rows = await self._s.scalars(
            select(t.AnnouncementRow)
            .where(t.AnnouncementRow.club_id == club_id)
            .order_by(t.AnnouncementRow.created_at.desc())
        )
        return [_load(Announcement, r) for r in rows]

    async def count_since(self, club_id: UUID, since: datetime) -> int:
        """Announcements created after `since`."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(t.AnnouncementRow)
            .where(
                t.AnnouncementRow.club_id == club_id,
                t.AnnouncementRow.created_at > since,
            )
        )
        return int(n or 0)

    async def list_scheduled(self) -> builtins.list[Announcement]:
        """Scheduled, unsent, uncancelled announcements."""
        rows = await self._s.scalars(
            select(t.AnnouncementRow).where(
                t.AnnouncementRow.scheduled_at.is_not(None),
                t.AnnouncementRow.sent_at.is_(None),
                t.AnnouncementRow.cancelled.is_(False),
            )
        )
        return [_load(Announcement, r) for r in rows]


def _item(row: Any) -> PlannerItem:
    return _load(PlannerItem, row, status=PlannerStatus)


class SqlPlannerRepository(_Repo):
    """Planner items."""

    async def add(self, item: PlannerItem) -> None:
        """Insert."""
        await self.save(item)

    async def get(self, item_id: UUID) -> PlannerItem | None:
        """One item."""
        row = await self._s.get(t.PlannerRow, item_id)
        return _item(row) if row else None

    async def save(self, item: PlannerItem) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.PlannerRow, item))

    async def list(self, club_id: UUID) -> builtins.list[PlannerItem]:
        """Items of a club."""
        rows = await self._s.scalars(
            select(t.PlannerRow).where(t.PlannerRow.club_id == club_id)
        )
        return [_item(r) for r in rows]


class SqlDraftRepository(_Repo):
    """Draft rounds, signups, picks and profiles."""

    async def add_round(self, rnd: DraftRound) -> None:
        """Insert a round."""
        await self._upsert(_dump(t.DraftRoundRow, rnd))

    async def get_round(self, round_id: UUID) -> DraftRound | None:
        """One round."""
        row = await self._s.get(t.DraftRoundRow, round_id)
        return _load(DraftRound, row) if row else None

    async def list_rounds(self, club_id: UUID) -> list[DraftRound]:
        """Rounds of a club."""
        rows = await self._s.scalars(
            select(t.DraftRoundRow).where(t.DraftRoundRow.club_id == club_id)
        )
        return [_load(DraftRound, r) for r in rows]

    async def add_signup(self, signup: DraftSignup) -> None:
        """Insert or update a signup."""
        await self._upsert(_dump(t.DraftSignupRow, signup))

    async def list_signups(self, round_id: UUID) -> list[DraftSignup]:
        """Signups of a round."""
        rows = await self._s.scalars(
            select(t.DraftSignupRow).where(t.DraftSignupRow.round_id == round_id)
        )
        return [_load(DraftSignup, r) for r in rows]

    async def add_pick(self, pick: DraftPick) -> None:
        """Insert a pick."""
        await self.save_pick(pick)

    async def get_pick(self, pick_id: UUID) -> DraftPick | None:
        """One pick."""
        row = await self._s.get(t.DraftPickRow, pick_id)
        return _load(DraftPick, row) if row else None

    async def save_pick(self, pick: DraftPick) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.DraftPickRow, pick))

    async def list_picks(self, round_id: UUID) -> list[DraftPick]:
        """Picks of a round."""
        rows = await self._s.scalars(
            select(t.DraftPickRow).where(t.DraftPickRow.round_id == round_id)
        )
        return [_load(DraftPick, r) for r in rows]

    async def list_picks_with_status(self, status: str) -> list[DraftPick]:
        """Picks in one status."""
        rows = await self._s.scalars(
            select(t.DraftPickRow).where(t.DraftPickRow.status == status)
        )
        return [_load(DraftPick, r) for r in rows]

    async def get_profile(self, user_id: UUID, club_id: UUID) -> ClubProfile | None:
        """A member's profile."""
        row = await self._s.get(t.ClubProfileRow, (user_id, club_id))
        return _load(ClubProfile, row) if row else None

    async def list_profiles(self, club_id: UUID) -> list[ClubProfile]:
        """Every profile of a club."""
        rows = await self._s.scalars(
            select(t.ClubProfileRow).where(t.ClubProfileRow.club_id == club_id)
        )
        return [_load(ClubProfile, r) for r in rows]

    async def save_profile(self, profile: ClubProfile) -> None:
        """Insert or update a profile."""
        await self._upsert(_dump(t.ClubProfileRow, profile))


class SqlPointsRepository(_Repo):
    """The points ledger and the opt-out list."""

    async def add(self, entry: PointEntry) -> bool:
        """Insert unless the source already awarded; True when added."""
        values = {
            "id": new_id(),
            "user_id": entry.user_id,
            "source_type": entry.source_type,
            "source_id": entry.source_id,
            "reason": entry.reason,
            "points": entry.points,
            "at": entry.at,
            "club_id": entry.club_id,
        }
        done = await self._s.scalar(
            insert(t.PointsRow)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["source_type", "source_id", "user_id", "reason"]
            )
            .returning(t.PointsRow.id)
        )
        return done is not None

    async def totals(
        self, club_id: UUID, since: datetime | None, until: datetime | None
    ) -> dict[UUID, int]:
        """Points per person on one club's ledger."""
        q = select(t.PointsRow.user_id, func.sum(t.PointsRow.points)).where(
            t.PointsRow.club_id == club_id
        )
        if since is not None:
            q = q.where(t.PointsRow.at >= since)
        if until is not None:
            q = q.where(t.PointsRow.at < until)
        rows = await self._s.execute(q.group_by(t.PointsRow.user_id))
        return {user: int(total) for user, total in rows}

    async def entries(self, club_id: UUID, user_id: UUID) -> list[PointEntry]:
        """One person's entries."""
        rows = await self._s.scalars(
            select(t.PointsRow)
            .where(t.PointsRow.club_id == club_id, t.PointsRow.user_id == user_id)
            .order_by(t.PointsRow.at)
        )
        return [
            PointEntry(
                r.user_id,
                r.source_type,
                r.source_id,
                r.reason,
                r.points,
                r.at,
                r.club_id,
            )
            for r in rows
        ]

    async def set_opt_out(self, user_id: UUID, opted_out: bool) -> None:
        """Hide a person's name on leaderboards."""
        if opted_out:
            await self._s.execute(
                insert(t.PointsOptOutRow)
                .values(user_id=user_id)
                .on_conflict_do_nothing()
            )
        else:
            row = await self._s.get(t.PointsOptOutRow, user_id)
            if row is not None:
                await self._s.delete(row)
        await self._s.flush()

    async def opted_out(self) -> set[UUID]:
        """People who opted out."""
        return set(await self._s.scalars(select(t.PointsOptOutRow.user_id)))


class SqlTeamRepository(_Repo):
    """Positions, applications and seats."""

    async def add_position(self, position: TeamPosition) -> None:
        """Insert."""
        await self._upsert(_dump(t.PositionRow, position))

    async def get_position(self, position_id: UUID) -> TeamPosition | None:
        """One position."""
        row = await self._s.get(t.PositionRow, position_id)
        return _load(TeamPosition, row) if row else None

    async def list_positions(self, club_id: UUID) -> list[TeamPosition]:
        """Positions of a club."""
        rows = await self._s.scalars(
            select(t.PositionRow)
            .where(t.PositionRow.club_id == club_id)
            .order_by(t.PositionRow.order)
        )
        return [_load(TeamPosition, r) for r in rows]

    async def add_application(self, application: PositionApplication) -> None:
        """Insert."""
        await self.save_application(application)

    async def get_application(self, application_id: UUID) -> PositionApplication | None:
        """One application."""
        row = await self._s.get(t.ApplicationRow, application_id)
        return _load(PositionApplication, row) if row else None

    async def save_application(self, application: PositionApplication) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.ApplicationRow, application))

    async def list_applications(self, position_id: UUID) -> list[PositionApplication]:
        """Applications to a position."""
        rows = await self._s.scalars(
            select(t.ApplicationRow).where(t.ApplicationRow.position_id == position_id)
        )
        return [_load(PositionApplication, r) for r in rows]

    async def count_accepted(self, position_id: UUID) -> int:
        """Accepted applications of a position."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(t.ApplicationRow)
            .where(
                t.ApplicationRow.position_id == position_id,
                t.ApplicationRow.status == "accepted",
            )
        )
        return int(n or 0)

    async def add_seat(self, seat: TeamSeat) -> None:
        """Insert."""
        await self.save_seat(seat)

    async def get_seat(self, seat_id: UUID) -> TeamSeat | None:
        """One seat."""
        row = await self._s.get(t.SeatRow, seat_id)
        return _load(TeamSeat, row) if row else None

    async def save_seat(self, seat: TeamSeat) -> None:
        """Insert or update."""
        await self._upsert(_dump(t.SeatRow, seat))

    async def list_seats(self, club_id: UUID) -> list[TeamSeat]:
        """Seats of a club."""
        rows = await self._s.scalars(
            select(t.SeatRow)
            .join(t.PositionRow, t.PositionRow.id == t.SeatRow.position_id)
            .where(t.PositionRow.club_id == club_id)
            .order_by(t.SeatRow.since)
        )
        return [_load(TeamSeat, r) for r in rows]

    async def add_consent_event(self, event: ConsentEvent) -> None:
        """Keep the consent history."""
        self._s.add(
            t.ConsentEventRow(
                id=new_id(), user_id=event.user_id, granted=event.granted, at=event.at
            )
        )
        await self._s.flush()


class SqlCourseLinkRepository(_Repo):
    """Club-course links."""

    async def add(self, link: ClubCourseLink) -> None:
        """Insert; a new request on a pair with an ended link replaces that row."""
        values = {f.name: getattr(link, f.name) for f in fields(link)}
        stmt = insert(t.ClubCourseRow).values(**values)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["club_id", "course_id"],
                set_={
                    k: v for k, v in values.items() if k not in ("club_id", "course_id")
                },
            )
        )
        await self._s.flush()

    async def save(self, link: ClubCourseLink) -> None:
        """Persist changes."""
        await self._s.execute(
            update(t.ClubCourseRow)
            .where(t.ClubCourseRow.id == link.id)
            .values(
                status=link.status,
                confirmed_by=link.confirmed_by,
                confirmed_at=link.confirmed_at,
            )
        )
        await self._s.flush()

    async def list_pair(self, club_id: UUID, course_id: UUID) -> list[ClubCourseLink]:
        """Every link of the pair, any status."""
        rows = await self._s.scalars(
            select(t.ClubCourseRow).where(
                t.ClubCourseRow.club_id == club_id,
                t.ClubCourseRow.course_id == course_id,
            )
        )
        return [_load(ClubCourseLink, r) for r in rows]

    async def list_for_club(self, club_id: UUID) -> list[ClubCourseLink]:
        """Pending and active links of a club."""
        rows = await self._s.scalars(
            select(t.ClubCourseRow).where(
                t.ClubCourseRow.club_id == club_id,
                t.ClubCourseRow.status.in_(_OPEN_LINK),
            )
        )
        return [_load(ClubCourseLink, r) for r in rows]

    async def list_for_course(self, course_id: UUID) -> list[ClubCourseLink]:
        """Pending and active links of a course."""
        rows = await self._s.scalars(
            select(t.ClubCourseRow).where(
                t.ClubCourseRow.course_id == course_id,
                t.ClubCourseRow.status.in_(_OPEN_LINK),
            )
        )
        return [_load(ClubCourseLink, r) for r in rows]
