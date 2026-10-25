"""The answer while it is written: a live draft, or one message edited once a second.

Private chats get `sendMessageDraft` (Bot API 9): the draft is ephemeral, so the
finished answer is always sent as a normal message. When drafts fail the stream
falls back to sending one message and editing it at most once a second. Nothing but
answer text is ever shown: no status lines, no tool steps, no empty draft (an empty
draft shows Telegram's own "Thinking…" placeholder, which may stay on screen).

The Bot API has no call that clears a draft: a draft disappears by itself after
about 30 seconds or as soon as the bot sends a message to the chat. So every turn
ends with a `sendMessage` (the answer, or an error notice), which removes it.
"""

import time
from collections.abc import Callable

from app.interfaces.bot.assistant.render import Chunk, render_draft
from app.interfaces.bot.utilities.reply_edit import is_not_modified

import structlog
from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = structlog.get_logger(__name__)

DRAFT_INTERVAL = 0.4
EDIT_INTERVAL = 1.0
TYPING_INTERVAL = 4.5  # the typing action lasts five seconds


class AnswerStream:
    """Shows the growing answer, then the final messages."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        draft_id: int,
        *,
        drafts: bool = True,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """`draft_id` must be non-zero; `drafts` False forces editing."""
        self.bot = bot
        self.chat_id = chat_id
        self.draft_id = draft_id or 1
        self.drafts = drafts and hasattr(bot, "send_message_draft")
        self.now = now
        self.message_id: int | None = None  # the edited message (fallback mode)
        self.shown = ""
        self.updated_at = float("-inf")
        self.typing_at = float("-inf")

    async def typing(self) -> None:
        """Keep the typing action on while the answer is prepared."""
        if self.now() - self.typing_at < TYPING_INTERVAL:
            return
        self.typing_at = self.now()
        try:
            await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
        except TelegramAPIError:
            log.info("bot.ai.typing_failed")

    async def update(self, markdown: str) -> None:
        """Show the answer so far (throttled; empty text is never shown)."""
        await self.typing()
        if not markdown.strip():
            return
        interval = DRAFT_INTERVAL if self.drafts else EDIT_INTERVAL
        if self.now() - self.updated_at < interval:
            return
        html = render_draft(markdown)
        if not html.strip() or html == self.shown:
            return
        self.updated_at = self.now()
        if self.drafts:
            try:
                await self.bot.send_message_draft(
                    chat_id=self.chat_id, draft_id=self.draft_id, text=html
                )
                self.shown = html
                return
            except TelegramAPIError as error:
                log.info("bot.ai.drafts_unavailable", error=str(error))
                self.drafts = False
        await self._put(html, None)

    async def _put(self, html: str, markup: InlineKeyboardMarkup | None) -> None:
        if self.message_id is None:
            sent = await self.bot.send_message(self.chat_id, html, reply_markup=markup)
            self.message_id = sent.message_id
        else:
            try:
                await self.bot.edit_message_text(
                    html,
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    reply_markup=markup,
                )
            except TelegramBadRequest as error:
                if not is_not_modified(error):
                    raise
        self.shown = html

    async def finish(
        self, chunks: list[Chunk], extra: list[list[InlineKeyboardButton]]
    ) -> None:
        """Send the final messages; `extra` buttons go under the last one."""
        for index, chunk in enumerate(chunks):
            rows = list(chunk.rows)
            if index == len(chunks) - 1:
                rows.extend(extra)
            markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
            if index == 0 and self.message_id is not None:
                await self._put(chunk.html, markup)
            else:
                await self.bot.send_message(
                    self.chat_id, chunk.html, reply_markup=markup
                )

    async def abort(self) -> None:
        """Remove the half-written message of the fallback mode."""
        if self.message_id is None:
            return
        try:
            await self.bot.delete_message(self.chat_id, self.message_id)
        except TelegramAPIError:
            log.info("bot.ai.abort_delete_failed")
        self.message_id = None
