"""The Today feed of the admission student: season, next steps, streak, deadlines.

Everything is computed from the student's own data by deterministic rules (see
`domain/today.py`); no model is called. Titles are localised here.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.calendar import CalendarService, Translate
from app.modules.admission.application.readiness import (
    COUNTRIES_QUESTION,
    ReadinessService,
)
from app.modules.admission.application.study_focus import load_study_focus
from app.modules.admission.domain.calendar import TASHKENT, CalendarEntry
from app.modules.admission.domain.tasks import Task
from app.modules.admission.domain.today import (
    DEADLINE_WINDOW_DAYS,
    MAX_DEADLINES,
    Candidate,
    Line,
    SeasonKey,
    Snapshot,
    auto_season,
    rank,
    season_lines,
    streak,
    urgent,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.settings_admission import ReadinessSettings
from app.shared.clock import Clock

GRADE_QUESTION: Final = "q08"
STREAK_LOOKBACK_DAYS: Final = 400
CALENDAR_HREF: Final = "/calendar/"
_DECIDED: Final = frozenset(
    {"admitted", "waitlisted", "deferred", "rejected", "enrolled"}
)
_SOURCE_MINUTES: Final = {
    "university": 60,
    "checklist": 20,
    "exam": 15,
    "opportunity": 45,
    "test_score": 15,
}
_TASK_MINUTES: Final = 30


@dataclass(frozen=True, slots=True)
class ChecklistLineView:
    """A localised checklist line."""

    key: str
    label: str
    done: bool
    progress: str | None
    href: str


@dataclass(frozen=True, slots=True)
class SeasonView:
    """The current season and its checklist."""

    key: SeasonKey
    source: str
    checklist: tuple[ChecklistLineView, ...]


@dataclass(frozen=True, slots=True)
class DeadlineView:
    """An upcoming deadline."""

    date: dt.date
    title: str
    list_entry_id: UUID | None
    kind: str
    href: str


@dataclass(frozen=True, slots=True)
class TodayView:
    """What the Today screen shows."""

    season: SeasonView
    next: tuple[Candidate, ...]
    streak_days: int
    today_done: bool
    last7: tuple[bool, ...]
    readiness_percent: int
    deadlines: tuple[DeadlineView, ...]


@dataclass(frozen=True, slots=True)
class _Data:
    """Everything read from the database for one feed."""

    profile: Any
    items: Sequence[Any]
    essays: Sequence[Any]
    scores: Sequence[Any]
    goals: Sequence[Any]
    checklist: Sequence[Any]
    tasks: Sequence[Task]
    entries: Sequence[Any]
    names: dict[UUID, str]
    focus: Any
    override: SeasonKey | None
    days: set[dt.date]


def _days_text(t: Translate, locale: str, days: int) -> str:
    if days < 0:
        return t(locale, "today-why-overdue", days=-days)
    if days == 0:
        return t(locale, "today-why-due-today")
    return t(locale, "today-why-due-days", days=days)


class TodayService:
    """Builds the feed for the signed-in student and stores the season override."""

    def __init__(
        self,
        uow_factory: UowFactory,
        readiness: ReadinessService,
        calendar: CalendarService,
        settings: ReadinessSettings,
        clock: Clock,
        t: Translate,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._readiness = readiness
        self._calendar = calendar
        self._cfg = settings
        self._clock = clock
        self._t = t

    async def set_season(self, ctx: AdmissionContext, key: SeasonKey | None) -> None:
        """Fix the season, or go back to the automatic one with None."""
        async with self._uow() as uow:
            await uow.today.set_season_override(ctx.user_id, key)
            await uow.commit()

    async def _load(self, student: UUID, today: dt.date) -> _Data:
        async with self._uow() as uow:
            entries = await uow.shortlist.entries(student)
            names: dict[UUID, str] = {}
            for e in entries:
                inst = await uow.catalog.institution(e.institution_id)
                names[e.id] = inst.name if inst is not None else ""
            return _Data(
                profile=await uow.profiles.get(student),
                items=await uow.items.list_for(student),
                essays=await uow.essays.list_for(student),
                scores=await uow.test_scores.entries(student),
                goals=await uow.goals.list_for(student),
                checklist=await uow.checklist.for_student(student),
                tasks=await uow.tasks.list_for(student),
                entries=entries,
                names=names,
                focus=await load_study_focus(uow, student),
                override=await uow.today.season_override(student),
                days=await uow.today.activity_days(
                    student, today - dt.timedelta(days=STREAK_LOOKBACK_DAYS)
                ),
            )

    def _snapshot(self, ctx: AdmissionContext, d: _Data) -> Snapshot:
        answers: dict[str, Any] = d.profile.answers if d.profile is not None else {}
        answered = answers.get(GRADE_QUESTION)
        grade = (
            None if ctx.grade is None else "grade_10" if ctx.grade <= 10 else "grade_11"
        )
        grade = grade or (answered if isinstance(answered, str) else None)
        applicable = [c for c in d.checklist if c.status != "n_a"]
        statements = [e for e in d.essays if e.list_entry_id is None]
        supplements = [e for e in d.essays if e.list_entry_id is not None]
        cfg = self._cfg
        today = self._clock.now().astimezone(TASHKENT).date()
        return Snapshot(
            grade=grade,
            list_size=len(d.entries),
            list_target=cfg.list_target,
            countries_answered=answers.get(COUNTRIES_QUESTION)
            not in (None, "", [], {}),
            major_chosen=bool(d.focus.chosen),
            activities_total=len(d.items),
            activities_ready=sum(1 for i in d.items if i.status == "ready"),
            activities_target=cfg.activities_target,
            tests_planned=sum(1 for s in d.scores if s.status != "score_received"),
            tests_received=len(
                {s.test_id for s in d.scores if s.status == "score_received"}
            ),
            tests_target=cfg.tests_target,
            plans=sum(1 for g in d.goals if g.status != "dropped"),
            plans_target=cfg.plans_target,
            statement_exists=bool(statements),
            statement_final=any(e.status == "final" for e in statements),
            supp_total=len(supplements),
            supp_final=sum(1 for e in supplements if e.status == "final"),
            docs_applicable=len(applicable),
            docs_done=sum(1 for c in applicable if c.status == "done"),
            tasks_overdue=sum(1 for x in d.tasks if x.is_overdue(today)),
            afford_known=sum(
                1 for e in d.entries if e.affordability_status != "unknown"
            ),
            applying=sum(1 for e in d.entries if e.status == "applying"),
            submitted=sum(1 for e in d.entries if e.status == "submitted"),
            decided=sum(1 for e in d.entries if e.status in _DECIDED),
            enrolled=sum(1 for e in d.entries if e.status == "enrolled"),
        )

    def _deadline_candidates(
        self,
        locale: str,
        today: dt.date,
        calendar: Sequence[CalendarEntry],
        tasks: Sequence[Task],
    ) -> list[Candidate]:
        t = self._t
        out: list[Candidate] = []
        for e in calendar:
            left = (e.day - today).days
            if urgent(left):
                out.append(
                    Candidate(
                        0,
                        left * 10,
                        f"deadline:{e.key}",
                        e.title,
                        _days_text(t, locale, left),
                        _SOURCE_MINUTES.get(e.source, 20),
                        e.url_path or CALENDAR_HREF,
                        str(e.list_entry_id) if e.list_entry_id else None,
                    )
                )
        for x in tasks:
            if x.status == "done" or x.deadline is None:
                continue
            left = (x.deadline - today).days
            if urgent(left):
                out.append(
                    Candidate(
                        0,
                        left * 10 + 1,
                        f"task:{x.id}",
                        x.title,
                        _days_text(t, locale, left),
                        _TASK_MINUTES,
                        "/tasks",
                        str(x.list_entry_id) if x.list_entry_id else None,
                    )
                )
        return out

    def _gap_candidates(
        self, locale: str, season: SeasonKey, lines: Sequence[Line], d: _Data
    ) -> list[Candidate]:
        t = self._t
        out: list[Candidate] = []
        season_name = t(locale, f"today-season-{season}")
        for i, line in enumerate(lines):
            if line.done:
                continue
            why = (
                t(
                    locale,
                    "today-why-line-progress",
                    season=season_name,
                    progress=line.progress,
                )
                if line.progress
                else t(locale, "today-why-line", season=season_name)
            )
            out.append(
                Candidate(
                    1,
                    i,
                    f"season:{season}:{line.key}",
                    t(locale, f"today-action-{line.key}"),
                    why,
                    line.minutes,
                    line.href,
                )
            )
        for i, e in enumerate(d.entries):
            if e.status in _DECIDED or e.affordability_status not in ("gap", "unknown"):
                continue
            out.append(
                Candidate(
                    2,
                    i,
                    f"fit:afford:{e.id}",
                    t(locale, "today-action-afford", name=d.names[e.id]),
                    t(locale, f"today-why-afford-{e.affordability_status}"),
                    15,
                    "/chooser/list/",
                    str(e.id),
                )
            )
        return out

    async def get(self, ctx: AdmissionContext, locale: str) -> TodayView:
        """The feed of the caller."""
        today = self._clock.now().astimezone(TASHKENT).date()
        d = await self._load(ctx.user_id, today)
        snap = self._snapshot(ctx, d)
        season: SeasonKey = d.override or auto_season(snap)
        lines = season_lines(season, snap)
        window = today + dt.timedelta(days=DEADLINE_WINDOW_DAYS)
        calendar = [
            e
            for e in await self._calendar.entries(ctx, today, window, locale)
            if e.day >= today
        ]
        cands = self._deadline_candidates(locale, today, calendar, d.tasks)
        cands += self._gap_candidates(locale, season, lines, d)
        run, today_done, last7 = streak(d.days, today)
        readiness = await self._readiness.get(ctx)
        return TodayView(
            season=SeasonView(
                key=season,
                source="override" if d.override else "auto",
                checklist=tuple(self._line(locale, ln) for ln in lines),
            ),
            next=tuple(rank(cands)),
            streak_days=run,
            today_done=today_done,
            last7=tuple(last7),
            readiness_percent=readiness.percent,
            deadlines=tuple(
                DeadlineView(
                    e.day,
                    e.title,
                    e.list_entry_id,
                    e.source,
                    e.url_path or CALENDAR_HREF,
                )
                for e in calendar[:MAX_DEADLINES]
            ),
        )

    def _line(self, locale: str, line: Line) -> ChecklistLineView:
        return ChecklistLineView(
            line.key,
            self._t(locale, f"today-check-{line.key}"),
            line.done,
            line.progress,
            line.href,
        )
