"""Use case: create an empty notebook (NB-1)."""

from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.notebook_fields import clean_emoji, clean_title
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.errors import NotebookLimitError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id


class CreateNotebook:
    """Creates a notebook of the student, up to `NOTEBOOKS__MAX_NOTEBOOKS`."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        locale: LocaleResolver,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.i18n = i18n
        self.locale = locale

    async def execute(
        self, actor: Actor, title: str | None = None, emoji: str | None = None
    ) -> Notebook:
        """Store a new notebook and return it.

        Without a title the notebook is called "Untitled notebook" in the student's
        language, and the title (and the emoji) may be replaced by the AI once the
        first source is read. A title or emoji given here is the student's own and
        is never replaced. A new notebook counts as opened, so it is listed first.
        """
        given_title = clean_title(title) if title and title.strip() else None
        given_emoji = clean_emoji(emoji)
        locale = await self.locale.locale_of(actor.user_id)
        now = self.clock.now()
        notebook = Notebook(
            id=new_id(),
            owner_id=actor.user_id,
            title=given_title or self.i18n.t(locale, "notebooks-default-title"),
            title_auto=given_title is None,
            emoji=given_emoji,
            emoji_auto=given_emoji is None,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
        )
        async with self.uow_factory() as uow:
            live = await uow.notebooks.count_live(actor.user_id)
            if live >= self.settings.notebooks.max_notebooks:
                raise NotebookLimitError(
                    params={"limit": self.settings.notebooks.max_notebooks}
                )
            await uow.notebooks.add(notebook)
            await uow.commit()
        return notebook
