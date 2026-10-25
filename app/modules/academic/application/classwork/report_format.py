"""Turns aggregated report rows into the ``AttendanceReport`` JSON."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.records import ReportRow
from app.modules.academic.domain.classwork.reports import rate

PERSON_VIEWS = {"student", "teacher"}


class ReportFormatter:
    """Resolves labels and computes rates."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    async def format(
        self,
        view: str,
        rows: list[ReportRow],
        locale: str,
        start: dt.date,
        end: dt.date,
    ) -> dict[str, Any]:
        """Return ``{"view", "from", "to", "rows"}`` with sorted, labelled rows."""
        people: dict[UUID, Person] = {}
        if view in PERSON_VIEWS:
            people = await self.people.people(UUID(row.key) for row in rows)
        ordered: list[tuple[tuple[str, str, int], dict[str, Any]]] = []
        for row in rows:
            label = self._label(view, row, locale, people)
            item = {
                "key": row.key,
                "label": label,
                "absences": row.absences,
                "excused": row.excused,
                "lessons": row.lessons,
                "rate": rate(row.absences, row.lessons),
                "not_taken": row.not_taken,
            }
            ordered.append((self._order(view, row, label), item))
        ordered.sort(key=lambda pair: pair[0])
        return {
            "view": view,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "rows": [item for _, item in ordered],
        }

    @staticmethod
    def _label(
        view: str, row: ReportRow, locale: str, people: dict[UUID, Person]
    ) -> str:
        if view in PERSON_VIEWS:
            person = people.get(UUID(row.key))
            return f"{person.last_name} {person.first_name}" if person else row.key
        if view == "subject":
            return localized(row.names, locale) or row.key
        if view == "lesson":
            subject = localized(row.names, locale)
            return f"{row.on} · {row.period} · {subject}".strip()
        return row.text or row.key

    @staticmethod
    def _order(view: str, row: ReportRow, label: str) -> tuple[str, str, int]:
        if view == "lesson":
            return (str(row.on or ""), label, row.period or 0)
        if view == "day":
            return (row.key, "", 0)
        return (label.casefold(), row.key, 0)
