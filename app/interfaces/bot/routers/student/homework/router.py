"""Router of the Homework screen (students)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.student.homework.handlers.mark_done import mark_done
from app.interfaces.bot.routers.student.homework.handlers.show_homework import (
    show_homework,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import HomeworkDoneCb, MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """Homework belongs to students."""
    router.message.filter(HasRole(Role.STUDENT))
    router.callback_query.filter(HasRole(Role.STUDENT))


def build_router() -> Router:
    """Build the homework router."""
    router = Router(name="student.homework")
    register_filters(router)
    router.message.register(show_homework, Command("homework"))
    router.callback_query.register(show_homework, MenuCb.filter(F.screen == "homework"))
    router.callback_query.register(mark_done, HomeworkDoneCb.filter())
    return router
