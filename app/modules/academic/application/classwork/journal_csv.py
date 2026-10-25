"""Use case: CSV export of the journal grid (STF-9)."""

from uuid import UUID

from app.modules.academic.application.classwork.csv_export import (
    journal_rows,
    render_csv,
)
from app.modules.academic.application.classwork.get_journal import GetJournal
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.shared.actor import Actor
from app.shared.i18n.core import I18nCore


class JournalCsv:
    """The grid with absences and marks, as a spreadsheet."""

    def __init__(
        self, journal: GetJournal, people: PeopleDirectory, i18n: I18nCore
    ) -> None:
        """Initialize the use case."""
        self.journal = journal
        self.people = people
        self.i18n = i18n

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        audience_key: str,
        term_id: UUID | None,
    ) -> bytes:
        """Return the CSV bytes (UTF-8 with BOM, ``;`` separated)."""
        data = await self.journal.execute(actor, subject_id, audience_key, term_id)
        locale = await self.people.locale(actor.user_id)
        return render_csv(journal_rows(data, lambda key: self.i18n.t(locale, key)))
