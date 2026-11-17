"""The deadline calendar: an aggregator of sources, the ICS feed and reminders.

`CalendarService` merges the entries of every registered `DeadlineSource`. The
built-in sources cover the university deadlines of the list, the checklist and
exam registration; other modules (opportunities) register their own.
"""

import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import OpportunityDeadline
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.application.test_scores import DatedScore
from app.modules.admission.domain.calendar import (
    DEFAULT_ALARM_OFFSETS,
    EXAMS,
    TASHKENT,
    CalendarEntry,
    CalendarFeed,
    ExamDate,
    clean_offsets,
    end_of_day,
    new_token,
    render_ics,
    token_hash,
)
from app.modules.admission.domain.classification import signals_of
from app.modules.admission.domain.documents import (
    REMINDER_CATCH_UP,
    ReminderPrefs,
    shift_out_of_quiet,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CalendarInputError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.runtime_settings import CALENDAR_ALARM_OFFSETS
from app.modules.admission.ports.calendar import CalendarStore, DeadlineSource
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

Translate = Callable[..., str]
"""`t(locale, key, **params)` over the backend locales."""

KNOWN_ROUNDS: Final = frozenset(
    {"ed", "ed2", "ea", "rea", "scea", "rd", "rolling", "other"}
)
"""Plan codes with a locale line `calendar-round-<code>`; others use `other`."""

MAX_RANGE_DAYS: Final = 400
FEED_PAST_DAYS: Final = 30
FEED_AHEAD_DAYS: Final = 400
REMINDER_LOCALE: Final = "ru"
"""Locale of the fallback title; the notification re-localises it by key."""
_CLOSED: Final = frozenset({"done", "n_a"})


def feed_path(token: str) -> str:
    """The public path of a feed, relative to the API origin."""
    return f"/v1/admission/calendar/{token}.ics"


def _title(t: Translate, locale: str, key: str, subject: str | None) -> str:
    text = t(locale, key)
    return f"{text} · {subject}" if subject else text


def _parse_day(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


class UniversitySource:
    """Deadlines of the institutions on the list, from the catalog facts."""

    name: Final = "university"

    def __init__(
        self, uow_factory: UowFactory, store: CalendarStore, t: Translate
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._store = store
        self._t = t

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Every published round deadline of every institution on the list.

        Only the round the student applies in is reminded; the others are shown
        so that an earlier round is not missed.
        """
        out: list[CalendarEntry] = []
        async with self._uow() as uow:
            listed = await uow.shortlist.entries(student_id)
            for e in listed:
                inst = await uow.catalog.institution(e.institution_id)
                fact = inst.fact("deadlines") if inst is not None else None
                if inst is None or fact is None or not isinstance(fact.value, list):
                    continue
                for raw in fact.value:
                    if not isinstance(raw, dict):
                        continue
                    day = _parse_day(raw.get("date"))
                    if day is None or not start <= day <= end:
                        continue
                    plan = str(raw.get("plan") or "other")
                    code = plan.lower()
                    key = f"calendar-round-{code if code in KNOWN_ROUNDS else 'other'}"
                    out.append(
                        CalendarEntry(
                            key=f"uni:{e.id}:{plan}:{day.isoformat()}",
                            source="university",
                            title=_title(self._t, locale, key, inst.name),
                            day=day,
                            due_utc=end_of_day(day),
                            url_path=f"/chooser/institution/?id={inst.id}",
                            predicted=not fact.verified,
                            remind=plan.upper() == e.round.upper(),
                            title_key=key,
                            subject=inst.name,
                        )
                    )
        return out

    async def students(self) -> Sequence[UUID]:
        """Every admission student."""
        return await self._store.admission_students()


class ChecklistSource:
    """Open checklist lines that carry a due date."""

    name: Final = "checklist"

    def __init__(
        self, uow_factory: UowFactory, store: CalendarStore, t: Translate
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._store = store
        self._t = t

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Lines not done or not applicable, due within the range."""
        out: list[CalendarEntry] = []
        async with self._uow() as uow:
            items = await uow.checklist.for_student(student_id)
            names: dict[UUID, str] = {}
            listed = {e.id: e for e in await uow.shortlist.entries(student_id)}
            for item in items:
                if item.status in _CLOSED or item.due_utc is None:
                    continue
                day = item.due_utc.astimezone(TASHKENT).date()
                if not start <= day <= end:
                    continue
                subject = None
                entry = listed.get(item.list_entry_id) if item.list_entry_id else None
                if entry is not None:
                    if entry.institution_id not in names:
                        inst = await uow.catalog.institution(entry.institution_id)
                        names[entry.institution_id] = inst.name if inst else ""
                    subject = names[entry.institution_id] or None
                key = f"calendar-item-{item.title_key}"
                out.append(
                    CalendarEntry(
                        key=f"check:{item.id}",
                        source="checklist",
                        title=_title(self._t, locale, key, subject),
                        day=day,
                        due_utc=item.due_utc,
                        all_day=False,
                        url_path="/documents/",
                        title_key=key,
                        subject=subject,
                    )
                )
        return out

    async def students(self) -> Sequence[UUID]:
        """Every admission student."""
        return await self._store.admission_students()


def planned_exams(answers: dict[str, Any]) -> frozenset[str]:
    """Exams the student plans to take, from the test answers of the profile."""
    signals = signals_of(answers)
    out: set[str] = set()
    if signals.english == "planned":
        out |= {"ielts", "toefl", "duolingo"}
    if signals.sat_act == "planned":
        out |= {"sat", "act"}
    return frozenset(out)


class ExamSource:
    """Registration deadlines and test days of exams the student plans."""

    name: Final = "exam"

    def __init__(
        self, uow_factory: UowFactory, store: CalendarStore, t: Translate
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._store = store
        self._t = t

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Registration deadlines (reminded) and test days (shown) in range."""
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
        wanted = planned_exams(profile.answers) if profile is not None else frozenset()
        if not wanted:
            return []
        out: list[CalendarEntry] = []
        for exam in await self._store.exam_dates():
            if exam.exam not in wanted:
                continue
            for kind, day, remind in (
                ("registration", exam.registration_deadline, True),
                ("day", exam.test_date, False),
            ):
                if not start <= day <= end:
                    continue
                key = f"calendar-exam-{kind}-{exam.exam}"
                out.append(
                    CalendarEntry(
                        key=f"exam:{exam.id}:{kind}",
                        source="exam",
                        title=_title(self._t, locale, key, None),
                        day=day,
                        due_utc=end_of_day(day),
                        url_path="/deadlines/",
                        remind=remind,
                        title_key=key,
                    )
                )
        return out

    async def students(self) -> Sequence[UUID]:
        """Every admission student."""
        return await self._store.admission_students()


OpportunityDeadlines = Callable[
    [UUID, dt.date, dt.date], Awaitable[list[OpportunityDeadline]]
]
"""The opportunity service's typed reader of deadlines in a requested range."""


class OpportunitySource:
    """Dated events of the opportunities a student saved."""

    name: Final = "opportunity"

    def __init__(
        self, deadlines_for: OpportunityDeadlines, store: CalendarStore
    ) -> None:
        """Keep the reader of opportunity deadlines and the student index."""
        self._deadlines_for = deadlines_for
        self._store = store

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Registration deadlines and events in range; projected ones are marked."""
        return [
            CalendarEntry(
                key=f"opp:{item.opportunity_id}:{item.kind}:{item.day.isoformat()}",
                source="opportunity",
                title=item.title,
                day=item.day,
                due_utc=end_of_day(item.day),
                url_path="/opportunities/",
                predicted=item.projected,
            )
            for item in await self._deadlines_for(student_id, start, end)
        ]

    async def students(self) -> Sequence[UUID]:
        """Every admission student."""
        return await self._store.admission_students()


ScoreDates = Callable[[UUID, dt.date, dt.date], Awaitable[list[DatedScore]]]
"""The test score service's reader of dated entries in a requested range."""


class ScoreCalendarSource:
    """Registration deadlines and test days of the tests a student tracks."""

    name: Final = "test_score"

    def __init__(self, dated: ScoreDates, store: CalendarStore, t: Translate) -> None:
        """Keep the reader of dated entries, the student index and translator."""
        self._dated = dated
        self._store = store
        self._t = t

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Both dates are reminded; the title names the test."""
        out: list[CalendarEntry] = []
        for item in await self._dated(student_id, start, end):
            key = f"calendar-test-{item.kind}"
            name = item.test.name(locale)
            if item.entry.label:
                name = f"{name} · {item.entry.label}"
            out.append(
                CalendarEntry(
                    key=f"tscore:{item.entry.id}:{item.kind}",
                    source="test_score",
                    title=_title(self._t, locale, key, name),
                    day=item.day,
                    due_utc=end_of_day(item.day),
                    url_path="/tests/",
                    remind=True,
                    title_key=key,
                    subject=name,
                )
            )
        return out

    async def students(self) -> Sequence[UUID]:
        """Every admission student."""
        return await self._store.admission_students()


@dataclass(frozen=True, slots=True)
class FeedStatus:
    """Whether the caller has a live feed; the token itself is never re-shown."""

    active: bool
    created_at: dt.datetime | None
    alarm_offsets: tuple[int, ...]
    default_offsets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class IssuedFeed:
    """A new feed: the token and its path are shown this once."""

    token: str
    path: str
    status: FeedStatus


def can_manage_calendar(ctx: AdmissionContext) -> bool:
    """Admins and staff with `deadlines:manage` keep exam dates."""
    if Role.ADMIN in ctx.actor.roles:
        return True
    return any(
        Permission.DEADLINES_MANAGE in a.role.effective_permissions
        for a in ctx.assignments
    )


class CalendarService:
    """Merges the sources; serves the calendar, the feed and the reminders."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        store: CalendarStore,
        runtime: RuntimeSettingsService,
        clock: Clock,
        t: Translate,
    ) -> None:
        """Keep the collaborators; the built-in sources are registered here."""
        self._uow = uow_factory
        self._access = access
        self._store = store
        self._runtime = runtime
        self._clock = clock
        self._t = t
        self._sources: list[DeadlineSource] = [
            UniversitySource(uow_factory, store, t),
            ChecklistSource(uow_factory, store, t),
            ExamSource(uow_factory, store, t),
        ]

    def register(self, source: DeadlineSource) -> None:
        """Add a source (call at bootstrap); entries appear everywhere at once."""
        self._sources.append(source)

    @property
    def store(self) -> CalendarStore:
        """The feed, reminder and exam-date store shared with extra sources."""
        return self._store

    @property
    def sources(self) -> tuple[str, ...]:
        """Names of the registered sources, in order."""
        return tuple(s.name for s in self._sources)

    async def _collect(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        out: list[CalendarEntry] = []
        for source in self._sources:
            out += await source.entries(student_id, start, end, locale)
        return sorted(out, key=lambda e: (e.day, e.due_utc, e.title))

    # -- authenticated ----------------------------------------------------

    async def entries(
        self,
        ctx: AdmissionContext,
        start: dt.date,
        end: dt.date,
        locale: str,
        student_id: UUID | None = None,
    ) -> list[CalendarEntry]:
        """The calendar of a student the caller may read, within the range."""
        if end < start or (end - start).days > MAX_RANGE_DAYS:
            raise CalendarInputError(params={"field": "to"})
        target = student_id or ctx.user_id
        await self._access.require(
            ctx, target, Permission.LIST_READ, object_type="calendar"
        )
        return await self._collect(target, start, end, locale)

    async def _defaults(self) -> tuple[int, ...]:
        raw = (await self._runtime.get()).get(CALENDAR_ALARM_OFFSETS, None)
        if isinstance(raw, list):
            cleaned = clean_offsets(o for o in raw if isinstance(o, int))
            if cleaned:
                return cleaned
        return DEFAULT_ALARM_OFFSETS

    async def _status(self, feed: CalendarFeed | None) -> FeedStatus:
        defaults = await self._defaults()
        if feed is None:
            return FeedStatus(False, None, defaults, defaults)
        return FeedStatus(
            True, feed.created_at, feed.alarm_offsets or defaults, defaults
        )

    async def _own(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})

    async def feed_status(self, ctx: AdmissionContext) -> FeedStatus:
        """The caller's own feed."""
        await self._own(ctx)
        return await self._status(await self._store.active_feed(ctx.user_id))

    async def issue_feed(self, ctx: AdmissionContext, locale: str) -> IssuedFeed:
        """Create or rotate the caller's feed; the old URL stops working."""
        await self._own(ctx)
        now = self._clock.now()
        old = await self._store.active_feed(ctx.user_id)
        token = new_token()
        feed = CalendarFeed(
            id=new_id(),
            user_id=ctx.user_id,
            token_hash=token_hash(token),
            locale=locale,
            alarm_offsets=old.alarm_offsets if old else None,
            created_at=now,
        )
        await self._store.replace_feed(feed, now)
        return IssuedFeed(token, feed_path(token), await self._status(feed))

    async def revoke_feed(self, ctx: AdmissionContext) -> None:
        """Revoke the caller's feed; unknown is not an error."""
        await self._own(ctx)
        await self._store.revoke_feeds(ctx.user_id, self._clock.now())

    async def set_alarms(
        self, ctx: AdmissionContext, offsets: Sequence[int]
    ) -> FeedStatus:
        """Set the feed's alarm offsets in days; an empty list means defaults."""
        await self._own(ctx)
        cleaned = clean_offsets(offsets)
        if not await self._store.set_alarms(ctx.user_id, cleaned):
            raise AdmissionNotFoundError()
        return await self._status(await self._store.active_feed(ctx.user_id))

    # -- public -----------------------------------------------------------

    async def ics(self, token: str) -> str:
        """The feed of a live token; unknown and revoked look the same (404)."""
        feed = await self._store.feed_by_hash(token_hash(token))
        if feed is None or feed.revoked_at is not None:
            raise AdmissionNotFoundError()
        today = self._clock.now().astimezone(TASHKENT).date()
        entries = await self._collect(
            feed.user_id,
            today - dt.timedelta(days=FEED_PAST_DAYS),
            today + dt.timedelta(days=FEED_AHEAD_DAYS),
            feed.locale,
        )
        return render_ics(
            entries,
            calendar_name=self._t(feed.locale, "calendar-feed-name"),
            user_key=feed.id.hex,
            alarm_offsets=feed.alarm_offsets or await self._defaults(),
            now=self._clock.now(),
        )

    # -- exam dates (staff) -------------------------------------------------

    def _need_manage(self, ctx: AdmissionContext) -> None:
        if not can_manage_calendar(ctx):
            raise AdmissionForbiddenError(
                params={"permission": Permission.DEADLINES_MANAGE.value}
            )

    async def exam_dates(self, ctx: AdmissionContext) -> list[ExamDate]:
        """All exam dates (staff)."""
        self._need_manage(ctx)
        return await self._store.exam_dates()

    async def add_exam_date(
        self,
        ctx: AdmissionContext,
        *,
        exam: str,
        test_date: dt.date,
        registration_deadline: dt.date,
        source_url: str | None,
    ) -> ExamDate:
        """Add an exam date; registration closes on or before the test day."""
        self._need_manage(ctx)
        if exam not in EXAMS:
            raise CalendarInputError(params={"field": "exam"})
        if registration_deadline > test_date:
            raise CalendarInputError(params={"field": "registration_deadline"})
        item = ExamDate(new_id(), exam, test_date, registration_deadline, source_url)
        await self._store.add_exam_date(item)
        return item

    async def delete_exam_date(self, ctx: AdmissionContext, exam_id: UUID) -> None:
        """Delete an exam date."""
        self._need_manage(ctx)
        if not await self._store.delete_exam_date(exam_id):
            raise AdmissionNotFoundError()

    # -- reminders ------------------------------------------------------------

    async def run_reminders(self) -> int:
        """Remind each student of reminded entries at their own offsets.

        A reminder fires once its moment (due minus offset) passed within the
        catch-up window; the ledger key makes it fire once, and quiet hours
        delay delivery. Returns the number of reminders queued.
        """
        now = self._clock.now()
        students: set[UUID] = set()
        for source in self._sources:
            students.update(await source.students())
        sent = 0
        for student_id in sorted(students):
            sent += await self._remind(student_id, now)
        return sent

    async def _remind(self, student_id: UUID, now: dt.datetime) -> int:
        async with self._uow() as uow:
            prefs = await uow.deadlines.prefs(student_id) or ReminderPrefs(student_id)
        if not prefs.offsets_days:
            return 0
        today = now.astimezone(TASHKENT).date()
        horizon = today + dt.timedelta(days=max(prefs.offsets_days) + 2)
        entries = await self._collect(
            student_id, today - dt.timedelta(days=1), horizon, REMINDER_LOCALE
        )
        sent = 0
        for e in entries:
            if not e.remind:
                continue
            for days in prefs.offsets_days:
                moment = e.due_utc - dt.timedelta(days=days)
                if not now - REMINDER_CATCH_UP < moment <= now:
                    continue
                key = f"calendar:{e.key}:{e.day.isoformat()}:{days}"
                if not await self._store.claim_reminder(key, student_id, now):
                    continue
                when = shift_out_of_quiet(now, prefs.quiet_from, prefs.quiet_to)
                async with self._uow() as uow:
                    uow.notify(
                        NotificationDraft(
                            user_id=student_id,
                            type=NotificationType.ADMISSION_DEADLINE_REMINDER,
                            payload={
                                "source": e.source,
                                "title": e.title,
                                "title_key": e.title_key,
                                "subject": e.subject,
                                "days": days,
                                "due_utc": e.due_utc.isoformat(),
                            },
                            dedupe_key=key,
                            scheduled_at=when if when > now else None,
                        )
                    )
                    await uow.commit()
                sent += 1
        return sent


__all__ = [
    "CalendarService",
    "ChecklistSource",
    "ExamSource",
    "FeedStatus",
    "IssuedFeed",
    "UniversitySource",
]
