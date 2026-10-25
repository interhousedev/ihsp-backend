"""Use case: CSV export of Administration's attendance report (ADM-12)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.classwork.attendance_report import (
    AttendanceReport,
)
from app.modules.academic.application.classwork.csv_export import (
    render_csv,
    report_rows,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.attendance_reports import (
    AdminView,
)
from app.shared.actor import Actor
from app.shared.i18n.core import I18nCore


class AttendanceReportCsv:
    """The same rows as the report, as a spreadsheet."""

    def __init__(
        self, report: AttendanceReport, people: PeopleDirectory, i18n: I18nCore
    ) -> None:
        """Initialize the use case."""
        self.report = report
        self.people = people
        self.i18n = i18n

    async def execute(
        self,
        actor: Actor,
        view: AdminView,
        start: dt.date | None,
        end: dt.date | None,
        group_id: UUID | None,
    ) -> bytes:
        """Return the CSV bytes (UTF-8 with BOM, ``;`` separated)."""
        data = await self.report.execute(actor, view, start, end, group_id)
        locale = await self.people.locale(actor.user_id)
        return render_csv(report_rows(data, lambda key: self.i18n.t(locale, key)))
