"""The title of an auto notebook in the language of the reader (NB-AUTO)."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.notebooks.application.auto_targets import title_with_suffix
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.domain.entities import Notebook
from app.shared.contracts.academic import ScheduleQueries


class NotebookTitles:
    """Replaces the stored title of subject-following notebooks by a fresh one.

    A notebook with a `subject_title_suffix` shows the subject's current name in the
    reader's language plus the suffix; any other title (typed by the user, or stored
    before the suffix existed) stays as it is. The entities are detached views:
    call this after the unit of work has committed, never before a save.
    """

    def __init__(self, locale: LocaleResolver, schedule: ScheduleQueries) -> None:
        """Store the collaborators."""
        self.locale = locale
        self.schedule = schedule

    async def apply(self, reader_id: UUID, notebooks: Iterable[Notebook]) -> None:
        """Set the title of each following notebook to the reader's language."""
        following = [
            x
            for x in notebooks
            if x.subject_title_suffix is not None and x.subject_id is not None
        ]
        if not following:
            return
        locale = await self.locale.locale_of(reader_id)
        ids = [x.subject_id for x in following if x.subject_id is not None]
        names = await self.schedule.subject_titles(ids, locale)
        for notebook in following:
            name = names.get(notebook.subject_id) if notebook.subject_id else None
            if name and notebook.subject_title_suffix is not None:
                notebook.title = title_with_suffix(name, notebook.subject_title_suffix)
