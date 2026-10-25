"""Screens of the guest mode: the /start choice and a post with its buttons."""

import re
from html import escape, unescape
from typing import Any, Final

from app.interfaces.bot.richtext import render_telegram
from app.interfaces.bot.routers.guest.callbacks import PostCb, StartModeCb
from app.modules.posts.application.bot_posts import PostScreen
from app.modules.posts.domain.post import pick
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

TELEGRAM_MAX: Final = 4096
HTML_TAG = re.compile(
    r"</?(b|strong|i|em|u|ins|s|strike|del|a|code|pre|blockquote|tg-spoiler|span)\b"
)


def build_choice(i18n: I18nContext) -> RenderedMessage:
    """Who are you: an Interhouse student or a guest."""
    return RenderedMessage(
        text_html=i18n("bot-guest-choice"),
        buttons=[
            [
                {
                    "text": i18n("bot-guest-btn-student"),
                    "callback_data": StartModeCb(mode="student").pack(),
                }
            ],
            [
                {
                    "text": i18n("bot-guest-btn-guest"),
                    "callback_data": StartModeCb(mode="guest").pack(),
                }
            ],
        ],
    )


def body_html(body: str) -> str:
    """Sanitized HTML is sent as is; anything else is Markdown for the renderer."""
    if not body:
        return ""
    if HTML_TAG.search(body):
        return body
    chunks = render_telegram(unescape(body))
    return "\n\n".join(chunk.text for chunk in chunks)


def build_post(
    screen: PostScreen, locale: str, i18n: I18nContext, *, guest: bool
) -> RenderedMessage:
    """The post text, its children, its link buttons, then Back and Main menu."""
    post = screen.post
    title = escape(pick(post.title, locale))
    body = body_html(pick(post.body, locale))
    text = f"<b>{title}</b>\n\n{body}" if body else f"<b>{title}</b>"
    if len(text) > TELEGRAM_MAX:  # the body limit keeps this rare; never split a post
        text = f"<b>{title}</b>\n\n{escape(unescape(pick(post.body, locale)))}"
        text = text[: TELEGRAM_MAX - 1] + "…"
    rows: list[list[dict[str, Any]]] = [
        [
            {
                "text": pick(child.title, locale),
                "callback_data": PostCb.of(child.id).pack(),
            }
        ]
        for child in screen.children
    ]
    rows.extend(
        [{"text": pick(button.label, locale), "url": button.url}]
        for button in post.buttons
    )
    if not post.is_root:
        back = PostCb.of(screen.parent_id).pack()
        nav = [{"text": i18n("bot-guest-btn-back"), "callback_data": back}]
        if screen.parent_id is not None:
            nav.append(
                {
                    "text": i18n("bot-guest-btn-main-menu"),
                    "callback_data": PostCb.of(None).pack(),
                }
            )
        rows.append(nav)
    elif guest:
        rows.append(
            [
                {
                    "text": i18n("bot-guest-btn-student"),
                    "callback_data": StartModeCb(mode="student").pack(),
                }
            ]
        )
    return RenderedMessage(text_html=text, buttons=rows)
