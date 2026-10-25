"""Router of the Current lesson screen (teachers)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.teacher.current_lesson.handlers.show_lesson import (
    show_current_lesson,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """The screen belongs to teachers."""
    router.message.filter(HasRole(Role.TEACHER))
    router.callback_query.filter(HasRole(Role.TEACHER))


def build_router() -> Router:
    """Build the current lesson router."""
    router = Router(name="teacher.current_lesson")
    register_filters(router)
    router.message.register(show_current_lesson, Command("lesson"))
    router.callback_query.register(
        show_current_lesson, MenuCb.filter(F.screen == "lesson")
    )
    return router
