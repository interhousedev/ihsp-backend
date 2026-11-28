"""Personal and milestone calendar sources and the one-off `.ics` export."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.application.calendar import (
    CalendarService,
    MilestoneSource,
    PersonalSource,
    month_end,
)
from app.modules.admission.application.personal_entries import PersonalEntryService
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    CalendarInputError,
)
from app.modules.admission.domain.goal_plan import GoalMilestone
from app.modules.admission.domain.personal_entries import PersonalDraft
from app.shared.actor import Role
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.paths import LOCALES_DIR
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.fakes_calendar import FakeCalendarStore
from tests.admission.unit.test_access_policy import OTHER, STUDENT
from tests.admission.unit.test_opportunities import CountingLimiter, Env
from tests.fakes.clock import FixedClock

import pytest

I18N = I18nCore(LOCALES_DIR).load()
TODAY = NOW.date()


class FakeGoals:
    def __init__(self) -> None:
        self.rows: list[GoalMilestone] = []

    async def list_for(self, student_id: UUID) -> list[GoalMilestone]:
        return [m for m in self.rows if m.student_id == student_id]


class FakeRuntime:
    async def get(self) -> dict[str, Any]:
        return {}


class CalEnv(Env):
    def __init__(self) -> None:
        super().__init__()
        self.goals = FakeGoals()
        self.store = FakeCalendarStore([STUDENT])
        base = self.uow

        def uow() -> FakeUow:
            u = base()
            u.goals = self.goals  # type: ignore[attr-defined]
            return u

        self.uow = uow
        self.personal = PersonalEntryService(
            uow,  # type: ignore[arg-type]
            self.w.policy,
            self.svc,
            FixedClock(NOW),
            CountingLimiter(),
        )
        self.cal = CalendarService(
            uow,  # type: ignore[arg-type]
            self.w.policy,
            self.store,  # type: ignore[arg-type]
            FakeRuntime(),  # type: ignore[arg-type]
            FixedClock(NOW),
            I18N.t,
        )
        self.cal.register(PersonalSource(uow, self.store, I18N.t))  # type: ignore
        self.cal.register(MilestoneSource(uow, self.store, I18N.t))  # type: ignore

    async def add(self, **kw: Any) -> UUID:
        base: dict[str, Any] = {"kind": "event", "title": "Robotics <camp>"}
        base.update(kw)
        added = await self.personal.add(await self.student(), PersonalDraft(**base))
        assert added.entry is not None
        return added.entry.id


def _days(n: int) -> dt.date:
    return TODAY + dt.timedelta(days=n)


async def test_personal_events_are_unverified_and_ends_not_reminded() -> None:
    e = CalEnv()
    eid = await e.add(
        registration_deadline=_days(10), starts_on=_days(20), ends_on=_days(30)
    )
    rows = await e.cal.entries(await e.student(), TODAY, _days(60), "en")
    mine = [r for r in rows if r.source == "personal"]
    assert [r.key for r in mine] == [
        f"personal:{eid}:registration",
        f"personal:{eid}:start",
        f"personal:{eid}:end",
    ]
    assert [r.remind for r in mine] == [True, True, False]
    assert all(r.subject == "Robotics <camp>" for r in mine)
    assert all("Not verified by the school" in (r.description or "") for r in mine)
    assert "personal" in e.cal.sources and "milestone" in e.cal.sources


async def test_milestones_only_planned_with_a_month() -> None:
    e = CalEnv()
    month = TODAY.replace(day=1) + dt.timedelta(days=40)
    month = month.replace(day=1)
    keep = GoalMilestone(new_id(), STUDENT, "IELTS 7", due_month=month)
    e.goals.rows = [
        keep,
        GoalMilestone(new_id(), STUDENT, "Done", due_month=month, status="done"),
        GoalMilestone(new_id(), STUDENT, "No month"),
        GoalMilestone(new_id(), OTHER, "Not mine", due_month=month),
    ]
    rows = await e.cal.entries(await e.student(), TODAY, _days(120), "en")
    [m] = [r for r in rows if r.source == "milestone"]
    assert m.key == f"goal:{keep.id}" and m.day == month_end(month)
    assert m.subject == "IELTS 7"


async def test_export_by_key_and_range() -> None:
    e = CalEnv()
    eid = await e.add(registration_deadline=_days(10), starts_on=_days(20))
    st = await e.student()
    one = await e.cal.export(st, "en", keys=[f"personal:{eid}:start"])
    assert one.count("BEGIN:VEVENT") == 1
    assert "Robotics <camp>" in one.replace("\r\n ", "")
    both = await e.cal.export(st, "en", start=TODAY, end=_days(30))
    assert both.count("BEGIN:VEVENT") == 2


async def test_export_rejects_bad_input_and_foreign_keys() -> None:
    e = CalEnv()
    eid = await e.add(registration_deadline=_days(10))
    st = await e.student()
    key = f"personal:{eid}:registration"
    with pytest.raises(CalendarInputError):
        await e.cal.export(st, "en", keys=[key, key])
    with pytest.raises(CalendarInputError):
        await e.cal.export(st, "en", keys=[f"k{i}" for i in range(51)])
    with pytest.raises(CalendarInputError):
        await e.cal.export(st, "en")
    with pytest.raises(CalendarInputError):
        await e.cal.export(st, "en", start=TODAY, end=_days(401))
    with pytest.raises(AdmissionNotFoundError):
        await e.cal.export(st, "en", keys=[f"personal:{new_id()}:registration"])
    other = await e.w.ctx(OTHER, Role.STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await e.cal.export(other, "en", keys=[key])
