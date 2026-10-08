"""Router of the attendance step of the end-of-lesson prompt (BOT-17)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.teacher.lesson_prompt.handlers.edit_attendance import (
    edit_attendance,
)
from app.interfaces.bot.routers.teacher.lesson_prompt.handlers.submit import (
    submit_attendance,
)
from app.interfaces.bot.routers.teacher.lesson_prompt.handlers.toggle_absent import (
    toggle_absent,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import AttActionCb, AttToggleCb

from aiogram import F, Router


def register_filters(router: Router) -> None:
    """The prompt belongs to teachers."""
    router.message.filter(HasRole(Role.TEACHER))
    router.callback_query.filter(HasRole(Role.TEACHER))


def build_router() -> Router:
    """Build the attendance prompt router."""
    router = Router(name="teacher.lesson_prompt")
    register_filters(router)
    router.callback_query.register(toggle_absent, AttToggleCb.filter())
    router.callback_query.register(
        submit_attendance, AttActionCb.filter(F.action.in_({"submit", "all_present"}))
    )
    router.callback_query.register(
        edit_attendance, AttActionCb.filter(F.action == "edit")
    )
    return router
