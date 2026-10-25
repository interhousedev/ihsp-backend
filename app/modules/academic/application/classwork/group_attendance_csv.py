"""Use case: CSV export of the curator's attendance report (STF-13)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.classwork.csv_export import (
    render_csv,
    report_rows,
)
from app.modules.academic.application.classwork.group_attendance import GroupAttendance
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.attendance_reports import (
    GroupView,
)
from app.shared.actor import Actor
from app.shared.i18n.core import I18nCore


class GroupAttendanceCsv:
    """The same rows as the report, as a spreadsheet."""

    def __init__(
        self, report: GroupAttendance, people: PeopleDirectory, i18n: I18nCore
    ) -> None:
        """Initialize the use case."""
        self.report = report
        self.people = people
        self.i18n = i18n

    async def execute(
        self,
        actor: Actor,
        group_id: UUID,
        view: GroupView,
        start: dt.date | None,
        end: dt.date | None,
    ) -> bytes:
        """Return the CSV bytes (UTF-8 with BOM, ``;`` separated)."""
        data = await self.report.execute(actor, group_id, view, start, end)
        locale = await self.people.locale(actor.user_id)
        return render_csv(report_rows(data, lambda key: self.i18n.t(locale, key)))
