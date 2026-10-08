"""The test harness: feed updates into the dispatcher, read what the bot did."""

from typing import Any

from tests.bot.support.fakes import STUDENT_TG, World
from tests.bot.support.recording_bot import (
    BOT_ID,
    RecordingSession,
    blocked_update,
    callback_update,
    document_update,
    message_update,
    session_of,
    voice_update,
)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendDocument,
    SendMessage,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class Harness:
    """Feeds updates into the dispatcher with the fake container."""

    def __init__(self, bot: Bot, dp: Dispatcher, world: World) -> None:
        """Bundle the bot, the dispatcher and the fakes."""
        self.bot, self.dp, self.world = bot, dp, world

    @property
    def session(self) -> RecordingSession:
        """The recording session of the bot."""
        return session_of(self.bot)

    async def send(
        self,
        text: str,
        *,
        user_id: int = STUDENT_TG,
        language: str | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> None:
        """The user sends a text message (``entities`` carry its formatting)."""
        update = message_update(
            self.bot, text, user_id=user_id, language=language, entities=entities
        )
        await self.dp.feed_update(self.bot, update, container=self.world.container)

    async def press(self, data: str, *, user_id: int = STUDENT_TG) -> None:
        """The user presses a button with this callback data."""
        update = callback_update(self.bot, data, user_id=user_id)
        await self.dp.feed_update(self.bot, update, container=self.world.container)

    async def send_document(
        self, *, user_id: int, file_name: str = "lecture.pdf", file_size: int = 1000
    ) -> None:
        """The user sends a document."""
        update = document_update(
            self.bot, user_id=user_id, file_name=file_name, file_size=file_size
        )
        await self.dp.feed_update(self.bot, update, container=self.world.container)

    async def send_voice(self, *, user_id: int) -> None:
        """The user sends a voice message."""
        update = voice_update(self.bot, user_id=user_id)
        await self.dp.feed_update(self.bot, update, container=self.world.container)

    async def block(self, *, kicked: bool, user_id: int = STUDENT_TG) -> None:
        """The user blocks (kicked) or unblocks the bot."""
        status = "kicked" if kicked else "member"
        update = blocked_update(self.bot, new_status=status, user_id=user_id)
        await self.dp.feed_update(self.bot, update, container=self.world.container)

    # - - - What the bot did - - -

    @property
    def sent(self) -> list[SendMessage]:
        """Messages the bot sent."""
        return self.session.calls(SendMessage)

    @property
    def edits(self) -> list[EditMessageText]:
        """Messages the bot edited."""
        return self.session.calls(EditMessageText)

    @property
    def documents(self) -> list[SendDocument]:
        """Documents the bot sent."""
        return self.session.calls(SendDocument)

    @property
    def toasts(self) -> list[AnswerCallbackQuery]:
        """Callback query answers."""
        return self.session.calls(AnswerCallbackQuery)

    def last(self) -> SendMessage | EditMessageText:
        """The last message the bot sent or edited."""
        shown = [
            r
            for r in self.session.requests
            if isinstance(r, SendMessage | EditMessageText)
        ]
        return shown[-1]

    def last_text(self) -> str:
        """Text of the last message."""
        text = self.last().text
        assert text is not None
        return text

    def last_buttons(self) -> list[list[InlineKeyboardButton]]:
        """Buttons of the last message, row by row."""
        markup = self.last().reply_markup
        assert isinstance(markup, InlineKeyboardMarkup)
        return markup.inline_keyboard

    def last_callbacks(self) -> list[str]:
        """Callback data of the last message's buttons, flat."""
        return [
            b.callback_data
            for row in self.last_buttons()
            for b in row
            if b.callback_data is not None
        ]

    def last_labels(self) -> list[str]:
        """Labels of the last message's buttons, flat."""
        return [b.text for row in self.last_buttons() for b in row]

    async def state_of(self, user_id: int) -> str | None:
        """The FSM state of a private chat."""
        key = StorageKey(bot_id=BOT_ID, chat_id=user_id, user_id=user_id)
        return await self.dp.storage.get_state(key)

    async def data_of(self, user_id: int) -> dict[str, object]:
        """The FSM data of a private chat."""
        key = StorageKey(bot_id=BOT_ID, chat_id=user_id, user_id=user_id)
        return await self.dp.storage.get_data(key)
