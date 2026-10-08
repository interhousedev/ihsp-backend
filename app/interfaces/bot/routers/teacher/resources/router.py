"""Router of adding a file or a link to a lesson from the bot (BOT-20)."""

from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    attach_resource,
)
from app.interfaces.bot.routers.teacher.resources.handlers.receive_document import (
    receive_document,
)
from app.interfaces.bot.routers.teacher.resources.handlers.receive_url import (
    receive_url,
)
from app.interfaces.bot.routers.teacher.resources.handlers.start_resource import (
    start_resource,
)
from app.interfaces.bot.routers.teacher.resources.states import ResourceStates
from app.shared.actor import Role
from app.shared.contracts.callbacks import ResourceLessonCb

from aiogram import F, Router
from aiogram.filters import StateFilter

URL_PATTERN = r"^https?://\S+$"


def register_filters(router: Router) -> None:
    """Resources belong to teachers."""
    router.message.filter(HasRole(Role.TEACHER))
    router.callback_query.filter(HasRole(Role.TEACHER))


def build_router() -> Router:
    """Build the resources router."""
    router = Router(name="teacher.resources")
    register_filters(router)
    waiting = StateFilter(None, ResourceStates.waiting_content)
    router.callback_query.register(
        start_resource, ResourceLessonCb.filter(F.role == "p")
    )
    router.message.register(receive_document, waiting, F.document)
    router.message.register(receive_url, waiting, F.text.regexp(URL_PATTERN))
    router.callback_query.register(
        attach_resource,
        StateFilter(ResourceStates.choosing),
        ResourceLessonCb.filter(F.role.in_({"m", "a"})),
    )
    return router
