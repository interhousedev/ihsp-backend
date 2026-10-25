"""Use case: save a chat answer as a note source (NB-8, § 3.3.6)."""

import re
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.answering import load_own_answer
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.note_sources import (
    create_note_source,
    note_title,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.i18n.core import I18nCore
from app.shared.tasks import TaskKicker
from app.shared.web_citations import chips_to_links, strip_chips

_CHIP = re.compile(r"\s*⟦[\d,\s]+⟧")


class SaveNote:
    """Turns an answer, with its citations, into a selected `note` source."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        locale: LocaleResolver,
        i18n: I18nCore,
        kicker: TaskKicker,
        clock: Clock,
        settings: Settings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.locale = locale
        self.i18n = i18n
        self.kicker = kicker
        self.clock = clock
        self.settings = settings

    async def execute(
        self, actor: Actor, notebook_id: UUID, message_id: UUID, title: str | None
    ) -> Source:
        """Create a pending note: the answer text with ``⟦n⟧`` and its citations.

        Web chips ``⟦w1⟧`` become Markdown links to the pages, which outlive the chat.

        The source is processed after the commit (``notebooks.process_source``).

        Args:
            actor: The student.
            notebook_id: The notebook.
            message_id: An assistant message of the student's own thread.
            title: The note title; the first words of the answer when empty.

        Raises:
            NotebookNotFoundError: Not the student's notebook or answer.
            InvalidOptionsError: The answer has no text.
            SourceLimitError: The notebook is full.
            SourceTooLargeError: The answer is over the per-source cap.
        """
        locale = await self.locale.locale_of(actor.user_id)
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            message = await load_own_answer(uow, actor.user_id, notebook_id, message_id)
            shown = message.content.text
            text = chips_to_links(shown, message.content.web)
            if not text.strip():
                raise InvalidOptionsError(params={"reason": "empty-answer"})
            fallback = self.i18n.t(locale, "notebooks-note-title-answer")
            source = await create_note_source(
                uow,
                notebook,
                owner_id=notebook.owner_id,
                title=note_title(title, _CHIP.sub("", strip_chips(shown)), fallback),
                body_md=text,
                citations=list(message.content.citations),
                now=self.clock.now(),
                settings=self.settings,
            )
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
            await uow.commit()
        return source
