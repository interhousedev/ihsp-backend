"""Use case: rename, pin or configure a notebook (NB-3)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.notebook_fields import (
    clean_emoji,
    clean_pinned,
    clean_title,
    invalid,
    merge_chat_config,
)
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

EDITABLE = frozenset({"title", "emoji", "pinned", "chat_config"})


class UpdateNotebook:
    """Applies the fields of a `PATCH /notebooks/{id}` to the student's notebook."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, changes: Mapping[str, Any]
    ) -> Notebook:
        """Change `title`, `emoji`, `pinned` and/or `chat_config`; return the result.

        A manual title or emoji is never replaced by the AI afterwards
        (`title_auto` / `emoji_auto` become false; `emoji: None` clears it). An
        unknown key or a value that is not allowed raises `InvalidOptionsError` and
        nothing is saved.
        """
        for key in changes:
            if key not in EDITABLE:
                raise invalid(key)
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            if changes:
                self._apply(notebook, changes)
                notebook.updated_at = self.clock.now()
                await uow.notebooks.save(notebook)
                await uow.commit()
        return notebook

    @staticmethod
    def _apply(notebook: Notebook, changes: Mapping[str, Any]) -> None:
        """Validate every change first, then set the fields."""
        title = clean_title(changes["title"]) if "title" in changes else None
        emoji = clean_emoji(changes["emoji"]) if "emoji" in changes else None
        pinned = clean_pinned(changes["pinned"]) if "pinned" in changes else None
        config = (
            merge_chat_config(notebook.chat_config, changes["chat_config"])
            if "chat_config" in changes
            else None
        )
        if title is not None:
            notebook.title = title
            notebook.title_auto = False
        if "emoji" in changes:
            notebook.emoji = emoji
            notebook.emoji_auto = False
        if pinned is not None:
            notebook.pinned = pinned
        if config is not None:
            notebook.chat_config = config
