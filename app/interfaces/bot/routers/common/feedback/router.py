"""Router of the feedback flow: linked users only, before the AI catch-all.

Every state handler here is registered for its state, so text typed during the
flow is taken by the flow and never reaches the assistant.
"""

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.feedback.attachments import (
    finish_attachments,
    hint_attachments,
    receive_file,
)
from app.interfaces.bot.routers.common.feedback.callbacks import (
    FeedbackAreaCb,
    FeedbackKindCb,
    FeedbackStepCb,
)
from app.interfaces.bot.routers.common.feedback.send import send_report
from app.interfaces.bot.routers.common.feedback.start import start
from app.interfaces.bot.routers.common.feedback.states import FeedbackStates
from app.interfaces.bot.routers.common.feedback.steps import (
    pick_area,
    pick_kind,
    receive_description,
    receive_title,
    reject_non_text,
    use_buttons,
)
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command, StateFilter


def build_router() -> Router:
    """Build the feedback router."""
    router = Router(name="common.feedback")
    router.message.filter(IsLinked())
    router.callback_query.filter(IsLinked())
    msg, cb = router.message, router.callback_query
    msg.register(start, Command("feedback"))
    cb.register(start, MenuCb.filter(F.screen == "feedback"))

    cb.register(pick_kind, StateFilter(FeedbackStates.kind), FeedbackKindCb.filter())
    cb.register(pick_area, StateFilter(FeedbackStates.area), FeedbackAreaCb.filter())
    msg.register(
        use_buttons,
        StateFilter(FeedbackStates.kind, FeedbackStates.area, FeedbackStates.confirm),
    )

    text_steps = StateFilter(FeedbackStates.title, FeedbackStates.description)
    msg.register(receive_title, StateFilter(FeedbackStates.title), F.text)
    msg.register(receive_description, StateFilter(FeedbackStates.description), F.text)
    msg.register(reject_non_text, text_steps)

    files = F.photo | F.document | F.video
    msg.register(receive_file, StateFilter(FeedbackStates.attachments), files)
    msg.register(hint_attachments, StateFilter(FeedbackStates.attachments))
    cb.register(
        finish_attachments,
        StateFilter(FeedbackStates.attachments),
        FeedbackStepCb.filter(F.action.in_({"done", "skip"})),
    )
    cb.register(
        send_report,
        StateFilter(FeedbackStates.confirm),
        FeedbackStepCb.filter(F.action == "send"),
    )
    return router
