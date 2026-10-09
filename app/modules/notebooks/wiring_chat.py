"""Wiring of the grounded chat slice (§ 3.3)."""

from dataclasses import dataclass

from app.modules.notebooks.application.ask_notebook import AskNotebook
from app.modules.notebooks.application.delete_chat import DeleteChat
from app.modules.notebooks.application.get_chat import GetChat
from app.modules.notebooks.application.message_feedback import MessageFeedback
from app.modules.notebooks.application.regenerate_chat import RegenerateChat
from app.modules.notebooks.application.save_note import SaveNote
from app.modules.notebooks.wiring_core import NotebooksCore


@dataclass(frozen=True, slots=True)
class ChatServices:
    """The chat use cases; each attribute is named after its file."""

    get_chat: GetChat
    ask_notebook: AskNotebook
    regenerate_chat: RegenerateChat
    delete_chat: DeleteChat
    message_feedback: MessageFeedback
    save_note: SaveNote


def build_chat(core: NotebooksCore) -> ChatServices:
    """Build the chat use cases over the shared services."""
    deps = core.deps
    return ChatServices(
        get_chat=GetChat(core.uow_factory),
        ask_notebook=AskNotebook(core),
        regenerate_chat=RegenerateChat(core),
        delete_chat=DeleteChat(core.uow_factory, core.turn_lock),
        message_feedback=MessageFeedback(core.uow_factory),
        save_note=SaveNote(
            uow_factory=core.uow_factory,
            locale=core.locale,
            i18n=deps.i18n,
            kicker=deps.kicker,
            clock=deps.clock,
            settings=deps.settings,
        ),
    )
