"""Router of the Today screen: teachers first, then students."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.common.today.handlers.show_today_student import (
    show_today_student,
)
from app.interfaces.bot.routers.common.today.handlers.show_today_teacher import (
    show_today_teacher,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def build_router() -> Router:
    """Build the Today router."""
    router = Router(name="common.today")
    today_cb = MenuCb.filter(F.screen == "today")
    teacher, student = HasRole(Role.TEACHER), HasRole(Role.STUDENT)
    router.message.register(show_today_teacher, Command("today"), teacher)
    router.callback_query.register(show_today_teacher, today_cb, teacher)
    router.message.register(show_today_student, Command("today"), student)
    router.callback_query.register(show_today_student, today_cb, student)
    return router
