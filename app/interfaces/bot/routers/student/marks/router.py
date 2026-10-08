"""Router of the Marks screen (students)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.student.marks.handlers.show_marks import show_marks
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """Marks belong to students."""
    router.message.filter(HasRole(Role.STUDENT))
    router.callback_query.filter(HasRole(Role.STUDENT))


def build_router() -> Router:
    """Build the marks router."""
    router = Router(name="student.marks")
    register_filters(router)
    router.message.register(show_marks, Command("marks"))
    router.callback_query.register(show_marks, MenuCb.filter(F.screen == "marks"))
    return router
