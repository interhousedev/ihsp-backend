"""Router of the student's mailbox: list, open, compose, reply, forward, spam."""

from app.interfaces.bot.callbacks import MailComposeCb
from app.interfaces.bot.filters.has_role import HasRole
from app.interfaces.bot.routers.student.mail.handlers.edit_draft import edit_draft
from app.interfaces.bot.routers.student.mail.handlers.mark_spam import mark_spam
from app.interfaces.bot.routers.student.mail.handlers.open_mail import open_mail
from app.interfaces.bot.routers.student.mail.handlers.receive_body import receive_body
from app.interfaces.bot.routers.student.mail.handlers.receive_note import receive_note
from app.interfaces.bot.routers.student.mail.handlers.receive_recipients import (
    receive_recipients,
)
from app.interfaces.bot.routers.student.mail.handlers.receive_subject import (
    receive_subject,
)
from app.interfaces.bot.routers.student.mail.handlers.reject_non_text import (
    reject_non_text,
)
from app.interfaces.bot.routers.student.mail.handlers.send_draft import send_draft
from app.interfaces.bot.routers.student.mail.handlers.show_full_mail import (
    show_full_mail,
)
from app.interfaces.bot.routers.student.mail.handlers.show_mail_list import (
    show_mail_list,
)
from app.interfaces.bot.routers.student.mail.handlers.skip_note import skip_note
from app.interfaces.bot.routers.student.mail.handlers.start_forward import start_forward
from app.interfaces.bot.routers.student.mail.handlers.start_new_mail import (
    start_new_mail,
)
from app.interfaces.bot.routers.student.mail.handlers.start_reply import start_reply
from app.interfaces.bot.routers.student.mail.handlers.unmark_spam import unmark_spam
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.shared.actor import Role
from app.shared.contracts.callbacks import MailCb, MailListCb, MenuCb

from aiogram import F, Router
from aiogram.filters import Command, StateFilter

TEXT_STATES = (
    MailStates.new_to,
    MailStates.new_subject,
    MailStates.new_body,
    MailStates.reply_body,
    MailStates.forward_to,
    MailStates.forward_note,
)


def register_filters(router: Router) -> None:
    """Mail belongs to students."""
    router.message.filter(HasRole(Role.STUDENT))
    router.callback_query.filter(HasRole(Role.STUDENT))


def _register_actions(router: Router) -> None:
    cb = router.callback_query
    cb.register(show_mail_list, MenuCb.filter(F.screen == "mail"))
    cb.register(show_mail_list, MailListCb.filter())
    cb.register(open_mail, MailCb.filter(F.action == "open"))
    cb.register(show_full_mail, MailCb.filter(F.action == "full"))
    cb.register(mark_spam, MailCb.filter(F.action == "spam"))
    cb.register(unmark_spam, MailCb.filter(F.action == "unspam"))
    cb.register(start_reply, MailCb.filter(F.action == "reply"))
    cb.register(start_forward, MailCb.filter(F.action == "fwd"))
    cb.register(start_new_mail, MailComposeCb.filter(F.action == "new"))


def _register_flow(router: Router) -> None:
    cb, msg = router.callback_query, router.message
    plain_text = F.text & ~F.text.startswith("/")
    msg.register(
        receive_recipients,
        StateFilter(MailStates.new_to, MailStates.forward_to),
        plain_text,
    )
    msg.register(receive_subject, StateFilter(MailStates.new_subject), plain_text)
    msg.register(
        receive_body,
        StateFilter(MailStates.new_body, MailStates.reply_body),
        plain_text,
    )
    msg.register(receive_note, StateFilter(MailStates.forward_note), plain_text)
    msg.register(reject_non_text, StateFilter(*TEXT_STATES), ~F.text)
    preview = StateFilter(MailStates.preview)
    cb.register(send_draft, preview, MailComposeCb.filter(F.action == "send"))
    cb.register(edit_draft, preview, MailComposeCb.filter(F.action == "edit"))
    cb.register(
        skip_note,
        StateFilter(MailStates.forward_note),
        MailComposeCb.filter(F.action == "skip"),
    )


def build_router() -> Router:
    """Build the mail router."""
    router = Router(name="student.mail")
    register_filters(router)
    router.message.register(show_mail_list, Command("mail"))
    _register_actions(router)
    _register_flow(router)
    return router
