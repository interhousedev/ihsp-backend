"""Router of the teacher's open work-offs (WO-7)."""

from app.interfaces.bot.callbacks import WorkOffDoneCb, WorkOffPageCb, WorkOffUndoCb
from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.teacher.work_offs.handlers.mark_done import mark_done
from app.interfaces.bot.routers.teacher.work_offs.handlers.show_work_offs import (
    show_work_offs,
)
from app.interfaces.bot.routers.teacher.work_offs.handlers.undo_done import undo_done
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """The quick done list belongs to teachers."""
    router.message.filter(HasRole(Role.TEACHER))
    router.callback_query.filter(HasRole(Role.TEACHER))


def build_router() -> Router:
    """Build the teacher work-offs router."""
    router = Router(name="teacher.work_offs")
    register_filters(router)
    router.message.register(show_work_offs, Command("workoffs"))
    cb = router.callback_query
    cb.register(show_work_offs, MenuCb.filter(F.screen == "workoffs"))
    cb.register(show_work_offs, WorkOffPageCb.filter())
    cb.register(mark_done, WorkOffDoneCb.filter())
    cb.register(undo_done, WorkOffUndoCb.filter())
    return router
