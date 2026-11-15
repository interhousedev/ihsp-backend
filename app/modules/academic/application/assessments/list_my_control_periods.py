"""The student's control periods (ПК 1, ПК 2, ИК) with exams left and marks taken."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.list_my_assessments import (
    ListMyAssessments,
)
from app.modules.academic.application.assessments.ports.unit_of_work import (
    AssessmentsUowFactory,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today

DEFAULT_PAST_DAYS = 200
DEFAULT_AHEAD_DAYS = 365


class ListMyControlPeriods:
    """Groups the student's controls by control week and joins the ПК/ИК marks."""

    def __init__(
        self,
        *,
        uow_factory: AssessmentsUowFactory,
        list_mine: ListMyAssessments,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._list_mine = list_mine
        self._clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        since: dt.date | None = None,
        until: dt.date | None = None,
    ) -> list[dict[str, Any]]:
        """Return the control weeks overlapping the window, oldest first.

        An exam is ``taken`` once it has a mark or its date has passed (a control
        week without a subject date counts as passed when the week is over); a taken
        exam without a mark has ``mark`` null. The mark is the student's ПК/ИК mark
        of the subject dated inside the control week.
        """
        today = local_today(self._clock)
        since = since or today - dt.timedelta(days=DEFAULT_PAST_DAYS)
        until = until or today + dt.timedelta(days=DEFAULT_AHEAD_DAYS)
        items = await self._list_mine.execute(actor, since=since, until=until)
        async with self._uow_factory() as uow:
            marks = await uow.reader.exam_marks(actor.user_id, since, until)
        periods: dict[tuple[str, dt.date, dt.date], dict[str, Any]] = {}
        for item in items:
            period, control = item["period"], item["control"]
            if period is None or control is None or item["status"] == "cancelled":
                continue
            key = (control, period["start"], period["end"])
            entry = periods.setdefault(
                key,
                {
                    "control": control,
                    "kind": item["kind"],
                    "start": period["start"],
                    "end": period["end"],
                    "exams": [],
                },
            )
            entry["exams"].append(_exam(item, marks, period, today))
        found = sorted(periods.values(), key=lambda p: (p["start"], p["control"]))
        for entry in found:
            entry["exams"].sort(
                key=lambda e: (e["date"] or entry["start"], e["subject"]["name"])
            )
        return found


def _exam(
    item: dict[str, Any],
    marks: dict[tuple[UUID, str], list[tuple[dt.date, int]]],
    period: dict[str, Any],
    today: dt.date,
) -> dict[str, Any]:
    subject_id = item["subject"]["id"]
    inside = [
        (day, value)
        for day, value in marks.get((subject_id, item["kind"]), [])
        if period["start"] <= day <= period["end"]
    ]
    mark = max(inside)[1] if inside else None
    dated = item["has_date"]
    over = (item["date"] < today) if dated else (period["end"] < today)
    return {
        "subject": item["subject"],
        "date": item["date"] if dated else None,
        "starts_at": item["starts_at"],
        "room": item["room"],
        "status": item["status"],
        "state": "taken" if mark is not None or over else "upcoming",
        "mark": mark,
    }
