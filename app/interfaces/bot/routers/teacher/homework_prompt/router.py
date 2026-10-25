"""Router of the homework step: add, preview, save, topic (BOT-17, BOT-18)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.ask_homework import (
    ask_homework,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.ask_topic import (
    ask_topic,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.cancel_draft import (
    cancel_homework,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.homework_text import (
    receive_homework_text,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.no_homework import (
    no_homework,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.not_text import (
    reject_non_text,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.save_homework import (
    save_homework,
)
from app.interfaces.bot.routers.teacher.homework_prompt.handlers.topic_text import (
    receive_topic_text,
)
from app.interfaces.bot.routers.teacher.homework_prompt.states import HomeworkStates
from app.shared.actor import Role
from app.shared.contracts.callbacks import HomeworkPromptCb

from aiogram import F, Router
from aiogram.filters import StateFilter


def register_filters(router: Router) -> None:
    """The homework step belongs to teachers."""
    router.message.filter(HasRole(Role.TEACHER))
    router.callback_query.filter(HasRole(Role.TEACHER))


def build_router() -> Router:
    """Build the homework prompt router."""
    router = Router(name="teacher.homework_prompt")
    register_filters(router)
    cb = router.callback_query
    confirm = StateFilter(HomeworkStates.confirm)
    cb.register(ask_homework, HomeworkPromptCb.filter(F.action == "add"))
    cb.register(ask_homework, confirm, HomeworkPromptCb.filter(F.action == "edit"))
    cb.register(ask_topic, HomeworkPromptCb.filter(F.action == "topic"))
    cb.register(no_homework, HomeworkPromptCb.filter(F.action == "none"))
    cb.register(save_homework, confirm, HomeworkPromptCb.filter(F.action == "save"))
    cb.register(cancel_homework, confirm, HomeworkPromptCb.filter(F.action == "cancel"))
    plain_text = F.text & ~F.text.startswith("/")
    router.message.register(
        receive_homework_text, StateFilter(HomeworkStates.waiting_text), plain_text
    )
    router.message.register(
        receive_topic_text, StateFilter(HomeworkStates.waiting_topic), plain_text
    )
    router.message.register(
        reject_non_text,
        StateFilter(HomeworkStates.waiting_text, HomeworkStates.waiting_topic),
        ~F.text,
    )
    return router
