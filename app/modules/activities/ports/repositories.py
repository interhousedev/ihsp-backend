"""Persistence ports of the activities module (one protocol per aggregate)."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.activities.domain.announcement import Announcement
from app.modules.activities.domain.club import Club, Declaration
from app.modules.activities.domain.course_link import ClubCourseLink
from app.modules.activities.domain.draft import (
    ClubProfile,
    DraftPick,
    DraftRound,
    DraftSignup,
)
from app.modules.activities.domain.event import Event, Rsvp
from app.modules.activities.domain.media import (
    Album,
    ClubMediaOverrides,
    Media,
    MediaBlock,
    MediaKind,
    MediaReport,
    MediaStatus,
)
from app.modules.activities.domain.membership import Membership
from app.modules.activities.domain.ownership import OwnershipTransfer
from app.modules.activities.domain.planner import PlannerItem
from app.modules.activities.domain.points import PointEntry
from app.modules.activities.domain.rating import Rating
from app.modules.activities.domain.report import EventReport
from app.modules.activities.domain.team import (
    ConsentEvent,
    PositionApplication,
    TeamPosition,
    TeamSeat,
)


class ClubRepository(Protocol):
    """Clubs and their declarations."""

    async def add(self, club: Club) -> None:
        """Insert a club."""

    async def save(self, club: Club) -> None:
        """Persist changes."""

    async def get(self, club_id: UUID) -> Club | None:
        """One club."""

    async def get_by_slug(self, slug: str) -> Club | None:
        """One club by slug."""

    async def list_all(self) -> list[Club]:
        """Every club."""

    async def add_declaration(self, declaration: Declaration) -> None:
        """Store a new declaration version."""

    async def latest_declaration(self, club_id: UUID) -> Declaration | None:
        """The newest declaration."""


class MembershipRepository(Protocol):
    """Memberships."""

    async def get(self, club_id: UUID, user_id: UUID) -> Membership | None:
        """One membership."""

    async def save(self, membership: Membership) -> None:
        """Insert or update."""

    async def list(self, club_id: UUID) -> builtins.list[Membership]:
        """All memberships of a club."""

    async def list_for_user(self, user_id: UUID) -> builtins.list[Membership]:
        """All memberships of a person."""


class TransferRepository(Protocol):
    """Ownership transfers."""

    async def add(self, transfer: OwnershipTransfer) -> None:
        """Insert."""

    async def get(self, transfer_id: UUID) -> OwnershipTransfer | None:
        """One transfer."""

    async def save(self, transfer: OwnershipTransfer) -> None:
        """Persist changes."""

    async def list_offered(
        self, club_id: UUID | None = None
    ) -> list[OwnershipTransfer]:
        """Open offers, optionally of one club."""


class EventRepository(Protocol):
    """Events, RSVPs and reports."""

    async def add(self, event: Event) -> None:
        """Insert an event."""

    async def get(self, event_id: UUID) -> Event | None:
        """One event."""

    async def save(self, event: Event) -> None:
        """Persist changes."""

    async def list_for_club(self, club_id: UUID) -> list[Event]:
        """Events of a club."""

    async def list_all(self) -> list[Event]:
        """Every event."""

    async def references_opportunity(self, opportunity_id: UUID) -> bool:
        """Whether an event points at the catalog entry."""

    async def get_rsvp(self, event_id: UUID, user_id: UUID) -> Rsvp | None:
        """One RSVP."""

    async def save_rsvp(self, rsvp: Rsvp) -> None:
        """Insert or update an RSVP."""

    async def list_rsvps(self, event_id: UUID) -> list[Rsvp]:
        """List the RSVPs of an event, oldest first."""

    async def get_report(self, event_id: UUID) -> EventReport | None:
        """The event report."""

    async def save_report(self, report: EventReport) -> None:
        """Insert or update the report."""


class RatingRepository(Protocol):
    """Ratings."""

    async def add(self, rating: Rating) -> None:
        """Insert."""

    async def get(self, rating_id: UUID) -> Rating | None:
        """One rating."""

    async def list_for(self, target_type: str, target_id: UUID) -> list[Rating]:
        """Ratings of one target."""


class AnnouncementRepository(Protocol):
    """Announcements."""

    async def add(self, announcement: Announcement) -> None:
        """Insert."""

    async def get(self, announcement_id: UUID) -> Announcement | None:
        """One announcement."""

    async def save(self, announcement: Announcement) -> None:
        """Persist changes."""

    async def list(self, club_id: UUID) -> builtins.list[Announcement]:
        """Announcements of a club, newest first."""

    async def count_since(self, club_id: UUID, since: datetime) -> int:
        """Announcements created after `since`."""

    async def list_scheduled(self) -> builtins.list[Announcement]:
        """Scheduled, unsent, uncancelled announcements."""


class PlannerRepository(Protocol):
    """Planner items."""

    async def add(self, item: PlannerItem) -> None:
        """Insert."""

    async def get(self, item_id: UUID) -> PlannerItem | None:
        """One item."""

    async def save(self, item: PlannerItem) -> None:
        """Persist changes."""

    async def list(self, club_id: UUID) -> builtins.list[PlannerItem]:
        """Items of a club."""


class DraftRepository(Protocol):
    """Draft rounds, signups, picks and member profiles."""

    async def add_round(self, rnd: DraftRound) -> None:
        """Insert a round."""

    async def get_round(self, round_id: UUID) -> DraftRound | None:
        """One round."""

    async def list_rounds(self, club_id: UUID) -> list[DraftRound]:
        """Rounds of a club."""

    async def add_signup(self, signup: DraftSignup) -> None:
        """Insert a signup."""

    async def list_signups(self, round_id: UUID) -> list[DraftSignup]:
        """Signups of a round."""

    async def add_pick(self, pick: DraftPick) -> None:
        """Insert a pick."""

    async def get_pick(self, pick_id: UUID) -> DraftPick | None:
        """One pick."""

    async def save_pick(self, pick: DraftPick) -> None:
        """Persist changes."""

    async def list_picks(self, round_id: UUID) -> list[DraftPick]:
        """Picks of a round."""

    async def list_picks_with_status(self, status: str) -> list[DraftPick]:
        """Picks in one status."""

    async def get_profile(self, user_id: UUID, club_id: UUID) -> ClubProfile | None:
        """A member's profile."""

    async def list_profiles(self, club_id: UUID) -> list[ClubProfile]:
        """Every member's stored answers for a club."""

    async def save_profile(self, profile: ClubProfile) -> None:
        """Insert or update a profile."""


class PointsRepository(Protocol):
    """The points ledger and the opt-out list."""

    async def add(self, entry: PointEntry) -> bool:
        """Insert unless the source already awarded; True when added."""

    async def totals(
        self, club_id: UUID, since: datetime | None, until: datetime | None
    ) -> dict[UUID, int]:
        """Points per person on one club's ledger."""

    async def entries(self, club_id: UUID, user_id: UUID) -> list[PointEntry]:
        """One person's entries."""

    async def set_opt_out(self, user_id: UUID, opted_out: bool) -> None:
        """Hide a person's name on leaderboards."""

    async def opted_out(self) -> set[UUID]:
        """People who opted out."""


class TeamRepository(Protocol):
    """Positions, applications and seats."""

    async def add_position(self, position: TeamPosition) -> None:
        """Insert."""

    async def get_position(self, position_id: UUID) -> TeamPosition | None:
        """One position."""

    async def list_positions(self, club_id: UUID) -> list[TeamPosition]:
        """Positions of a club."""

    async def add_application(self, application: PositionApplication) -> None:
        """Insert."""

    async def get_application(self, application_id: UUID) -> PositionApplication | None:
        """One application."""

    async def save_application(self, application: PositionApplication) -> None:
        """Persist changes."""

    async def list_applications(self, position_id: UUID) -> list[PositionApplication]:
        """Applications to a position."""

    async def count_accepted(self, position_id: UUID) -> int:
        """Accepted applications of a position."""

    async def add_seat(self, seat: TeamSeat) -> None:
        """Insert."""

    async def get_seat(self, seat_id: UUID) -> TeamSeat | None:
        """One seat."""

    async def save_seat(self, seat: TeamSeat) -> None:
        """Persist changes."""

    async def list_seats(self, club_id: UUID) -> list[TeamSeat]:
        """Seats of a club."""

    async def add_consent_event(self, event: ConsentEvent) -> None:
        """Keep the consent history."""


class CourseLinkRepository(Protocol):
    """Club-course links."""

    async def add(self, link: ClubCourseLink) -> None:
        """Insert."""

    async def save(self, link: ClubCourseLink) -> None:
        """Persist changes."""

    async def list_pair(self, club_id: UUID, course_id: UUID) -> list[ClubCourseLink]:
        """Every link of the pair, any status."""

    async def list_for_club(self, club_id: UUID) -> list[ClubCourseLink]:
        """Pending and active links of a club."""

    async def list_for_course(self, course_id: UUID) -> list[ClubCourseLink]:
        """Pending and active links of a course."""


class AlbumRepository(Protocol):
    """Albums (folders of club media)."""

    async def add(self, album: Album) -> None:
        """Insert."""

    async def save(self, album: Album) -> None:
        """Persist changes (soft delete included)."""

    async def get(self, album_id: UUID) -> Album | None:
        """One album, deleted or not."""

    async def get_by_source_ref(self, source_ref: str) -> Album | None:
        """The album an import already created."""

    async def root_for_event(self, event_id: UUID) -> Album | None:
        """The live root album of an event."""

    async def list_children(
        self, club_id: UUID, parent_id: UUID | None
    ) -> builtins.list[Album]:
        """Live albums under a parent (None = top level), newest event date first."""

    async def item_counts(
        self, album_ids: builtins.list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        """``(ready items, live folders)`` per album."""


class MediaRepository(Protocol):
    """Media items, reports, upload blocks and per-club limit overrides."""

    async def add(self, media: Media) -> None:
        """Insert."""

    async def save(self, media: Media) -> None:
        """Persist changes."""

    async def remove(self, media_id: UUID) -> None:
        """Delete the row for good (a failed upload)."""

    async def get(self, media_id: UUID) -> Media | None:
        """One item, any status."""

    async def get_many(self, media_ids: builtins.list[UUID]) -> builtins.list[Media]:
        """Items by id (unknown ids are absent)."""

    async def get_by_source_ref(self, source_ref: str) -> Media | None:
        """The item an import already created."""

    async def find_duplicate(self, album_id: UUID, sha256: str) -> Media | None:
        """A non-deleted item of the album with the same content."""

    async def list_album(
        self,
        album_id: UUID,
        *,
        statuses: frozenset[MediaStatus],
        kind: MediaKind | None,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> builtins.list[Media]:
        """Items ordered by ``(position, id)``, after the cursor."""

    async def list_for_announcement(
        self, announcement_id: UUID
    ) -> builtins.list[Media]:
        """Photos of an announcement ordered by position."""

    async def count_album(self, album_id: UUID) -> int:
        """Items of an album that are not deleted or failed."""

    async def next_position(self, album_id: UUID) -> int:
        """One past the highest position in the album."""

    async def used_bytes(self, club_id: UUID) -> int:
        """Sum of ``byte_size`` of the club's items that are not deleted."""

    async def used_bytes_locked(self, club_id: UUID) -> int:
        """``used_bytes`` holding the club's quota lock until the transaction ends."""

    async def item_count(self, club_id: UUID) -> int:
        """The club's items that are not deleted."""

    async def add_report(self, report: MediaReport) -> None:
        """Insert."""

    async def get_report(self, report_id: UUID) -> MediaReport | None:
        """One report."""

    async def save_report(self, report: MediaReport) -> None:
        """Persist changes."""

    async def reports_for(self, media_id: UUID) -> builtins.list[MediaReport]:
        """All reports of an item, oldest first."""

    async def list_for_review(
        self, state: str, club_id: UUID | None, limit: int, offset: int
    ) -> tuple[builtins.list[Media], int]:
        """``state``: ``reported`` (open reports), ``hidden``; items and the total."""

    async def list_deleted_before(self, cutoff: datetime) -> builtins.list[Media]:
        """Soft-deleted items older than the cutoff whose files still exist."""

    async def list_stale(
        self, usage_staged: bool, status: MediaStatus, cutoff: datetime
    ) -> builtins.list[Media]:
        """Items in ``status`` (staged ones when asked) created before the cutoff."""

    async def add_block(self, block: MediaBlock) -> None:
        """Bar a user; repeating for the same scope is a no-op."""

    async def remove_block(self, user_id: UUID, club_id: UUID | None) -> None:
        """Lift a block."""

    async def is_blocked(self, user_id: UUID, club_id: UUID) -> bool:
        """Barred in this club or everywhere."""

    async def list_blocks(self, club_id: UUID | None) -> builtins.list[MediaBlock]:
        """Blocks of a club (None = the global ones)."""

    async def overrides(self, club_id: UUID) -> ClubMediaOverrides:
        """Limit overrides of the club; all ``None`` when unset."""

    async def set_overrides(self, club_id: UUID, value: ClubMediaOverrides) -> None:
        """Replace the club's overrides; ``None`` fields clear them."""
