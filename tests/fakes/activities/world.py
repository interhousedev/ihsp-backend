"""In-memory world for the activities application tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.activities.domain.errors import PermissionDeniedError
from app.modules.activities.domain.team import TeamSeat
from app.modules.activities.ports.bundle import Ports
from app.modules.activities.ports.gateways import CatalogEntry, MediaConfig
from app.modules.activities.wiring import ActivitiesServices, build
from app.shared.actor import Actor, Role
from app.shared.base_error import RateLimitedError
from app.shared.notifications import NotificationType
from tests.fakes.activities.media import (
    AlbumsFake,
    MediaFake,
    MediaKickerFake,
    MediaProcessorFake,
    MediaStoreFake,
)
from tests.fakes.clock import FixedClock

from uuid_utils.compat import uuid7


@dataclass
class SentRow:
    """One notification row; the delivery channel is not part of it."""

    user_id: UUID
    type: NotificationType
    payload: dict[str, Any]
    dedupe_key: str
    scheduled_at: datetime | None = None


@dataclass
class Course:
    """A course known to the lookup port."""

    id: UUID
    owner_id: UUID
    teacher_ids: set[UUID] = field(default_factory=set)

    @property
    def teacher_id(self) -> UUID:
        """The owning teacher."""
        return self.owner_id


class NotifierFake:
    """Immediate rows go to `sent`, future ones to `scheduled`, then `delivered`."""

    def __init__(self, clock: FixedClock) -> None:
        """Start empty."""
        self._clock = clock
        self.sent: list[SentRow] = []
        self.scheduled: list[SentRow] = []
        self.delivered: list[SentRow] = []
        self._keys: set[str] = set()

    async def send(self, drafts: list[Any]) -> None:
        """Insert rows; a repeated dedupe key is dropped."""
        for d in drafts:
            if d.dedupe_key in self._keys:
                continue
            self._keys.add(d.dedupe_key)
            row = SentRow(
                d.user_id, d.type, dict(d.payload), d.dedupe_key, d.scheduled_at
            )
            if d.scheduled_at is not None and d.scheduled_at > self._clock.now():
                self.scheduled.append(row)
            else:
                self.sent.append(row)

    async def cancel_scheduled(
        self, prefix: str, *, user_id: UUID | None = None
    ) -> None:
        """Drop pending rows; the key stays reserved only for delivered ones."""
        keep = []
        for r in self.scheduled:
            if r.dedupe_key.startswith(prefix) and (
                user_id is None or r.user_id == user_id
            ):
                self._keys.discard(r.dedupe_key)
            else:
                keep.append(r)
        self.scheduled[:] = keep

    def deliver_due(self) -> None:
        """Move due scheduled rows to delivered."""
        now = self._clock.now()
        due = [
            r
            for r in self.scheduled
            if r.scheduled_at is not None and r.scheduled_at <= now
        ]
        self.scheduled[:] = [r for r in self.scheduled if r not in due]
        self.delivered.extend(due)


class _Store:
    """Dict-backed storage that copies on the way in and out."""

    def __init__(self) -> None:
        self.rows: dict[Any, Any] = {}

    def put(self, key: Any, row: Any) -> None:
        self.rows[key] = deepcopy(row)

    def get(self, key: Any) -> Any:
        return deepcopy(self.rows.get(key))

    def all(self) -> list[Any]:
        return [deepcopy(r) for r in self.rows.values()]


class _ById(_Store):
    async def add(self, row: Any) -> None:
        self.put(row.id, row)

    async def save(self, row: Any) -> None:
        self.put(row.id, row)


class ClubsFake(_ById):
    def __init__(self) -> None:
        super().__init__()
        self.declarations: list[Any] = []

    async def add(self, club: Any) -> None:  # type: ignore[override]
        self.put(club.id, club)

    async def get(self, club_id: UUID) -> Any:  # type: ignore[override]
        return super().get(club_id)

    async def get_by_slug(self, slug: str) -> Any:
        return next((c for c in self.all() if c.slug == slug), None)

    async def list_all(self) -> list[Any]:
        return self.all()

    async def add_declaration(self, declaration: Any) -> None:
        self.declarations.append(deepcopy(declaration))

    async def latest_declaration(self, club_id: UUID) -> Any:
        mine = [d for d in self.declarations if d.club_id == club_id]
        return deepcopy(max(mine, key=lambda d: d.version)) if mine else None


class MembersFake(_Store):
    async def get(self, club_id: UUID, user_id: UUID) -> Any:  # type: ignore[override]
        return super().get((club_id, user_id))

    async def save(self, m: Any) -> None:
        self.put((m.club_id, m.user_id), m)

    async def list(self, club_id: UUID) -> list[Any]:
        return [m for m in self.all() if m.club_id == club_id]

    async def list_for_user(self, user_id: UUID) -> list[Any]:
        return [m for m in self.all() if m.user_id == user_id]


class TransfersFake(_ById):
    async def get(self, transfer_id: UUID) -> Any:  # type: ignore[override]
        return super().get(transfer_id)

    async def list_offered(self, club_id: UUID | None = None) -> list[Any]:
        return [
            t
            for t in self.all()
            if str(t.status) == "offered" and (club_id is None or t.club_id == club_id)
        ]


class EventsFake(_ById):
    def __init__(self) -> None:
        super().__init__()
        self.rsvps = _Store()
        self.reports = _Store()

    async def get(self, event_id: UUID) -> Any:  # type: ignore[override]
        return super().get(event_id)

    async def list_for_club(self, club_id: UUID) -> list[Any]:
        return [e for e in self.all() if e.club_id == club_id]

    async def list_all(self) -> list[Any]:
        return self.all()

    async def references_opportunity(self, opportunity_id: UUID) -> bool:
        return any(e.opportunity_id == opportunity_id for e in self.all())

    async def get_rsvp(self, event_id: UUID, user_id: UUID) -> Any:
        return self.rsvps.get((event_id, user_id))

    async def save_rsvp(self, rsvp: Any) -> None:
        self.rsvps.put((rsvp.event_id, rsvp.user_id), rsvp)

    async def list_rsvps(self, event_id: UUID) -> list[Any]:
        return sorted(
            (r for r in self.rsvps.all() if r.event_id == event_id),
            key=lambda r: r.created_at,
        )

    async def get_report(self, event_id: UUID) -> Any:
        return self.reports.get(event_id)

    async def save_report(self, report: Any) -> None:
        self.reports.put(report.event_id, report)


class RatingsFake(_ById):
    async def get(self, rating_id: UUID) -> Any:  # type: ignore[override]
        return super().get(rating_id)

    async def list_for(self, target_type: str, target_id: UUID) -> list[Any]:
        return [
            r
            for r in self.all()
            if r.target_type == target_type and r.target_id == target_id
        ]


class AnnouncementsFake(_ById):
    async def get(self, announcement_id: UUID) -> Any:  # type: ignore[override]
        return super().get(announcement_id)

    async def list(self, club_id: UUID) -> list[Any]:
        rows = [a for a in self.all() if a.club_id == club_id]
        return sorted(rows, key=lambda a: a.created_at, reverse=True)

    async def count_since(self, club_id: UUID, since: datetime) -> int:
        return sum(
            1 for a in self.all() if a.club_id == club_id and a.created_at > since
        )

    async def list_scheduled(self) -> list[Any]:
        return [
            a
            for a in self.all()
            if a.scheduled_at is not None and a.sent_at is None and not a.cancelled
        ]


class ContactRelayFake:
    """Telegram relay: owners in `reachable_ids` get messages, kept in `delivered`."""

    def __init__(self) -> None:
        self.reachable_ids: set[UUID] = set()
        self.delivered: list[dict[str, Any]] = []

    async def reachable(self, user_id: UUID) -> bool:
        return user_id in self.reachable_ids

    async def deliver(self, user_id: UUID, **message: Any) -> bool:
        if user_id not in self.reachable_ids:
            return False
        self.delivered.append({"user_id": user_id, **message})
        return True


class PlannerFake(_ById):
    async def get(self, item_id: UUID) -> Any:  # type: ignore[override]
        return super().get(item_id)

    async def list(self, club_id: UUID) -> list[Any]:
        return [i for i in self.all() if i.club_id == club_id]


class DraftsFake:
    def __init__(self) -> None:
        self.rounds, self.signups, self.picks = _Store(), _Store(), _Store()
        self.profiles = _Store()

    async def add_round(self, rnd: Any) -> None:
        self.rounds.put(rnd.id, rnd)

    async def get_round(self, round_id: UUID) -> Any:
        return self.rounds.get(round_id)

    async def list_rounds(self, club_id: UUID) -> list[Any]:
        return [r for r in self.rounds.all() if r.club_id == club_id]

    async def add_signup(self, signup: Any) -> None:
        self.signups.put(signup.id, signup)

    async def list_signups(self, round_id: UUID) -> list[Any]:
        return [s for s in self.signups.all() if s.round_id == round_id]

    async def add_pick(self, pick: Any) -> None:
        self.picks.put(pick.id, pick)

    async def get_pick(self, pick_id: UUID) -> Any:
        return self.picks.get(pick_id)

    async def save_pick(self, pick: Any) -> None:
        self.picks.put(pick.id, pick)

    async def list_picks(self, round_id: UUID) -> list[Any]:
        return [p for p in self.picks.all() if p.round_id == round_id]

    async def list_picks_with_status(self, status: str) -> list[Any]:
        return [p for p in self.picks.all() if p.status == status]

    async def get_profile(self, user_id: UUID, club_id: UUID) -> Any:
        return self.profiles.get((user_id, club_id))

    async def list_profiles(self, club_id: UUID) -> list[Any]:
        return [deepcopy(p) for (_, c), p in self.profiles.rows.items() if c == club_id]

    async def save_profile(self, profile: Any) -> None:
        self.profiles.put((profile.user_id, profile.club_id), profile)


class PointsFake:
    def __init__(self) -> None:
        self.entries_: list[Any] = []
        self.out: set[UUID] = set()

    async def add(self, entry: Any) -> bool:
        if any(
            (e.club_id, e.source_type, e.source_id, e.user_id)
            == (entry.club_id, entry.source_type, entry.source_id, entry.user_id)
            for e in self.entries_
        ):
            return False
        self.entries_.append(deepcopy(entry))
        return True

    async def totals(
        self, club_id: UUID, since: datetime | None, until: datetime | None
    ) -> dict[UUID, int]:
        out: dict[UUID, int] = {}
        for e in self.entries_:
            if (
                e.club_id != club_id
                or (since and e.at < since)
                or (until and e.at >= until)
            ):
                continue
            out[e.user_id] = out.get(e.user_id, 0) + e.points
        return out

    async def entries(self, club_id: UUID, user_id: UUID) -> list[Any]:
        return [
            deepcopy(e)
            for e in self.entries_
            if e.club_id == club_id and e.user_id == user_id
        ]

    async def set_opt_out(self, user_id: UUID, opted_out: bool) -> None:
        (self.out.add if opted_out else self.out.discard)(user_id)

    async def opted_out(self) -> set[UUID]:
        return set(self.out)


class TeamFake:
    def __init__(self) -> None:
        self.positions, self.applications, self.seats = _Store(), _Store(), _Store()
        self.consents: list[Any] = []

    async def add_position(self, position: Any) -> None:
        self.positions.put(position.id, position)

    async def get_position(self, position_id: UUID) -> Any:
        return self.positions.get(position_id)

    async def list_positions(self, club_id: UUID) -> list[Any]:
        return [p for p in self.positions.all() if p.club_id == club_id]

    async def add_application(self, application: Any) -> None:
        self.applications.put(application.id, application)

    async def get_application(self, application_id: UUID) -> Any:
        return self.applications.get(application_id)

    async def save_application(self, application: Any) -> None:
        self.applications.put(application.id, application)

    async def list_applications(self, position_id: UUID) -> list[Any]:
        return [a for a in self.applications.all() if a.position_id == position_id]

    async def count_accepted(self, position_id: UUID) -> int:
        return sum(
            1
            for a in self.applications.all()
            if a.position_id == position_id and str(a.status) == "accepted"
        )

    async def add_seat(self, seat: Any) -> None:
        self.seats.put(seat.id, seat)

    async def get_seat(self, seat_id: UUID) -> Any:
        return self.seats.get(seat_id)

    async def save_seat(self, seat: Any) -> None:
        self.seats.put(seat.id, seat)

    async def list_seats(self, club_id: UUID) -> list[Any]:
        club_positions = {p.id for p in await self.list_positions(club_id)}
        return [s for s in self.seats.all() if s.position_id in club_positions]

    async def add_consent_event(self, event: Any) -> None:
        self.consents.append(deepcopy(event))


class LinksFake(_ById):
    async def list_pair(self, club_id: UUID, course_id: UUID) -> list[Any]:
        return [
            k for k in self.all() if k.club_id == club_id and k.course_id == course_id
        ]

    async def list_for_club(self, club_id: UUID) -> list[Any]:
        return [
            k
            for k in self.all()
            if k.club_id == club_id and k.status in ("pending", "active")
        ]

    async def list_for_course(self, course_id: UUID) -> list[Any]:
        return [
            k
            for k in self.all()
            if k.course_id == course_id and k.status in ("pending", "active")
        ]


class UsersFake:
    def __init__(self) -> None:
        self.names: dict[UUID, str] = {}
        self.ages: dict[UUID, int] = {}
        self.students: set[UUID] = set()
        self.roles: dict[UUID, set[Role]] = {}
        self.final_year: set[UUID] = set()

    async def display_name(self, user_id: UUID) -> str:
        return self.names.get(user_id, "")

    async def age(self, user_id: UUID) -> int | None:
        return self.ages.get(user_id)

    async def is_student(self, user_id: UUID) -> bool:
        return user_id in self.students

    async def holders(self, role: Role) -> list[UUID]:
        return [u for u, rs in self.roles.items() if role in rs]

    async def graduating(self) -> set[UUID]:
        return set(self.final_year)


class CoursesFake:
    def __init__(self) -> None:
        self.rows: dict[UUID, Course] = {}

    async def exists(self, course_id: UUID) -> bool:
        return course_id in self.rows

    async def is_staff(self, course_id: UUID, user_id: UUID) -> bool:
        c = self.rows.get(course_id)
        return c is not None and (user_id == c.owner_id or user_id in c.teacher_ids)


class CaptchaFake:
    def __init__(self) -> None:
        self.ok = True

    async def verify(self, token: str, ip: str) -> bool:
        return self.ok


class RateLimiterFake:
    """Fixed windows measured by the injected clock."""

    def __init__(self, clock: FixedClock) -> None:
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        now = self._clock.now().timestamp()
        start, count = self._hits.get(key, (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        if count > limit:
            raise RateLimitedError()
        return count


@dataclass(frozen=True)
class AuditRow:
    actor_id: UUID
    action: str
    target: UUID | None


class AuditFake(list[AuditRow]):
    async def record(self, actor_id: UUID, action: str, target: UUID | None) -> None:
        self.append(AuditRow(actor_id, action, target))


class CatalogFake:
    def __init__(self) -> None:
        self.rows: dict[UUID, CatalogEntry] = {}
        self.plans: list[tuple[UUID, UUID]] = []
        self.legacy_status: dict[UUID, str] = {}

    async def get(self, opportunity_id: UUID) -> CatalogEntry | None:
        return deepcopy(self.rows.get(opportunity_id))

    async def list_all(self) -> list[CatalogEntry]:
        return deepcopy(list(self.rows.values()))

    async def references_ok(self, draft: Any) -> str | None:
        return None

    async def apply(
        self, draft: Any, audience: frozenset[str], *, target_id: UUID | None, by: UUID
    ) -> UUID:
        oid = target_id or uuid7()
        old = self.rows.get(oid)
        self.rows[oid] = CatalogEntry(
            oid,
            draft,
            audience,
            old.archived if old else False,
            old.lock_version + 1 if old else 1,
        )
        return oid

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        e = self.rows[opportunity_id]
        self.rows[opportunity_id] = CatalogEntry(
            e.id, e.draft, e.audience, archived, e.lock_version
        )

    async def in_use(self, opportunity_id: UUID) -> bool:
        return any(o == opportunity_id for _, o in self.plans)

    async def delete(self, opportunity_id: UUID) -> None:
        self.rows.pop(opportunity_id, None)


class AdmissionFake:
    """Admission student data reader."""

    def __init__(self, catalog: CatalogFake) -> None:
        self._catalog = catalog

    async def student_plans(self, actor: Actor, student_id: UUID) -> list[UUID]:
        if actor.user_id != student_id and Role.ADMIN not in actor.roles:
            raise PermissionDeniedError()
        return [o for s, o in self._catalog.plans if s == student_id]


class ActivitiesWorld:
    """Services over in-memory ports plus handles to inspect and drive them."""

    def __init__(self) -> None:
        self.clock = FixedClock()
        self.notifier = NotifierFake(self.clock)
        self.captcha = CaptchaFake()
        self.relay = ContactRelayFake()
        self.rate_limiter = RateLimiterFake(self.clock)
        self.audit = AuditFake()
        self.users = UsersFake()
        self.courses = CoursesFake()
        self.catalog = CatalogFake()
        self.admission = AdmissionFake(self.catalog)
        self.team = TeamFake()
        self.media_store = MediaStoreFake()
        self.media_processor = MediaProcessorFake()
        self.media_kicker = MediaKickerFake()
        ports = Ports(
            clubs=ClubsFake(),  # type: ignore[arg-type]
            members=MembersFake(),  # type: ignore[arg-type]
            transfers=TransfersFake(),  # type: ignore[arg-type]
            events=EventsFake(),  # type: ignore[arg-type]
            ratings=RatingsFake(),  # type: ignore[arg-type]
            announcements=AnnouncementsFake(),  # type: ignore[arg-type]
            planner=PlannerFake(),  # type: ignore[arg-type]
            drafts=DraftsFake(),  # type: ignore[arg-type]
            points=PointsFake(),  # type: ignore[arg-type]
            team=self.team,  # type: ignore[arg-type]
            links=LinksFake(),  # type: ignore[arg-type]
            notifier=self.notifier,
            users=self.users,
            courses=self.courses,
            captcha=self.captcha,
            contact_relay=self.relay,  # type: ignore[arg-type]
            limiter=self.rate_limiter,
            audit=self.audit,
            catalog=self.catalog,
            clock=self.clock,
            secret="test-secret",
            ip_salt="test-salt",
            albums=AlbumsFake(),  # type: ignore[arg-type]
            media=MediaFake(),  # type: ignore[arg-type]
            media_store=self.media_store,
            media_processor=self.media_processor,
            media_kicker=self.media_kicker,
            media_config=MediaConfig(quota_bytes=1000, photo_max_bytes=500),
        )
        self.ports = ports
        self.services: ActivitiesServices = build(ports)

    @property
    def sent(self) -> list[SentRow]:
        return self.notifier.sent

    @property
    def scheduled(self) -> list[SentRow]:
        return self.notifier.scheduled

    @property
    def delivered(self) -> list[SentRow]:
        return self.notifier.delivered

    def deliver_due(self) -> None:
        """Deliver scheduled rows that are due."""
        self.notifier.deliver_due()

    def _person(
        self, roles: set[Role], *, age: int = 18, name: str | None = None
    ) -> Actor:
        uid = uuid7()
        self.users.names[uid] = name or f"Person {str(uid)[:8]}"
        self.users.ages[uid] = age
        self.users.roles[uid] = set(roles)
        if Role.STUDENT in roles:
            self.users.students.add(uid)
        return Actor(user_id=uid, roles=frozenset(roles))

    def name_of(self, actor: Actor) -> str:
        """Display name of a person."""
        return self.users.names[actor.user_id]

    def add_student(self, *, age: int = 16, **kw: Any) -> Actor:
        """A student."""
        return self._person({Role.STUDENT}, age=age, **kw)

    def add_staff(self, *roles: Role) -> Actor:
        """A staff member with the given roles."""
        return self._person(set(roles), age=35)

    def add_teacher(self, **kw: Any) -> Actor:
        """A teacher."""
        return self._person({Role.TEACHER}, age=35, **kw)

    def add_course(self, *, teacher: Actor, **kw: Any) -> Course:
        """A course owned by the teacher."""
        course = Course(uuid7(), teacher.user_id, {teacher.user_id})
        self.courses.rows[course.id] = course
        return course

    def remove_teacher(self, course: Course, teacher: Actor) -> None:
        """The teacher loses the course."""
        c = self.courses.rows[course.id]
        c.teacher_ids.discard(teacher.user_id)
        if c.owner_id == teacher.user_id:
            c.owner_id = UUID(int=0)

    def add_legacy_opportunity(self, status: str = "approved") -> CatalogEntry:
        """A row as it exists before the audience migration (empty audience)."""
        from app.modules.admission.domain.opportunities import OpportunityDraft

        oid = uuid7()
        entry = CatalogEntry(
            oid,
            OpportunityDraft(kind="exam", title=f"Legacy {status}"),
            frozenset(),
            False,
            1,
        )
        self.catalog.rows[oid] = entry
        self.catalog.legacy_status[oid] = status
        return entry

    def run_audience_migration(self) -> None:
        """The backfill: approved legacy rows are shown on both surfaces."""
        for oid, status in self.catalog.legacy_status.items():
            e = self.catalog.rows[oid]
            if status == "approved" and not e.audience:
                self.catalog.rows[oid] = CatalogEntry(
                    e.id,
                    e.draft,
                    frozenset({"admission", "my_iht"}),
                    e.archived,
                    e.lock_version,
                )

    def add_student_plan(self, student: Actor, opportunity_id: UUID) -> None:
        """A student planned an opportunity."""
        self.catalog.plans.append((student.user_id, UUID(str(opportunity_id))))

    def plans_of(self, student: Actor) -> list[UUID]:
        """Opportunities the student planned."""
        return [o for s, o in self.catalog.plans if s == student.user_id]

    def add_team_seat(
        self,
        club_id: UUID,
        actor: Actor,
        position: str,
        bio: Any = None,
        photo_url: str | None = None,
        public: bool = False,
        consent: bool = False,
    ) -> TeamSeat:
        """A seat on the club team (and its position) added directly."""
        from app.modules.activities.domain.team import TeamPosition

        club_id = UUID(str(club_id))
        pos_id = uuid7()
        pos = TeamPosition(pos_id, club_id, position, None, 1, False, {})
        seat = TeamSeat(
            pos_id,
            actor.user_id,
            datetime.now(UTC),
            None,
            public,
            consent,
            bio,
            [],
            photo_url,
        )
        self.team.positions.rows[pos_id] = pos
        self.team.seats.put(seat.id, seat)
        return seat


def build_world() -> ActivitiesWorld:
    """A fresh world."""
    return ActivitiesWorld()
