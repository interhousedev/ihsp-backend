"""A bot whose session records every request instead of calling Telegram.

Results (or exceptions) can be
queued per method class; unqueued calls get a harmless default.
"""

import datetime as dt
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, File, Message, Update

BOT_ID = 42
NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


class RecordingSession(BaseSession):
    """Records requests; ``download_data`` is what file downloads return."""

    def __init__(self) -> None:
        """Start with no requests and an empty download."""
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.download_data = b""
        self._queued: dict[type, deque[Any]] = defaultdict(deque)

    def queue(self, method_cls: type, result: Any) -> None:
        """Return ``result`` (or raise it, if an exception) for the next call."""
        self._queued[method_cls].append(result)

    def calls(self, method_cls: type) -> list[Any]:
        """Return the recorded requests of one method class."""
        return [m for m in self.requests if isinstance(m, method_cls)]

    async def close(self) -> None:
        """Nothing to close."""

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        """Record the request and answer with a queued or default result."""
        self.requests.append(method)
        queued = self._queued.get(type(method))
        if queued:
            result = queued.popleft()
            if isinstance(result, Exception):
                raise result
            return result
        return self._default(method)

    @staticmethod
    def _default(method: TelegramMethod[Any]) -> Any:
        name = type(method).__name__
        if name == "GetFile":
            return File(file_id="f", file_unique_id="u", file_path="docs/file.bin")
        returning = str(method.__returning__)
        if "Message" in returning and "MessageId" not in returning:
            chat_id = getattr(method, "chat_id", 1)
            return Message(
                message_id=1,
                date=NOW,
                text=getattr(method, "text", None),
                chat=Chat(
                    id=chat_id if isinstance(chat_id, int) else 1, type="private"
                ),
            )
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Yield the configured download data."""
        yield self.download_data


def make_bot() -> Bot:
    """A bot with a recording session; the token only has to look like one."""
    return Bot(f"{BOT_ID}:TEST", session=RecordingSession())


def session_of(bot: Bot) -> RecordingSession:
    """The bot's recording session, typed."""
    assert isinstance(bot.session, RecordingSession)
    return bot.session


def _sender(user_id: int, *, language: str | None = None) -> dict[str, Any]:
    sender: dict[str, Any] = {"id": user_id, "is_bot": False, "first_name": "Test"}
    if language:
        sender["language_code"] = language
    return sender


def _message(user_id: int, message_id: int, **content: Any) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "date": int(NOW.timestamp()),
        "chat": {"id": user_id, "type": "private"},
        "from": _sender(user_id),
        **content,
    }


def _update(bot: Bot, update_id: int, **payload: Any) -> Update:
    return Update.model_validate(
        {"update_id": update_id, **payload}, context={"bot": bot}
    )


def message_update(
    bot: Bot,
    text: str,
    *,
    user_id: int = 1001,
    update_id: int = 1,
    language: str | None = None,
    entities: list[dict[str, Any]] | None = None,
) -> Update:
    """A text message; commands get the bot_command entity."""
    message = _message(user_id, update_id, text=text)
    if language:
        message["from"] = _sender(user_id, language=language)
    if entities:
        message["entities"] = entities
    if text.startswith("/"):
        length = len(text.split()[0])
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": length}]
    return _update(bot, update_id, message=message)


def callback_update(
    bot: Bot,
    data: str,
    *,
    user_id: int = 1001,
    update_id: int = 2,
    message_id: int = 10,
) -> Update:
    """A button press on a message the bot sent earlier."""
    bot_message = _message(user_id, message_id, text="previous")
    bot_message["from"] = {"id": BOT_ID, "is_bot": True, "first_name": "Bot"}
    query = {
        "id": f"cb{update_id}",
        "chat_instance": "ci",
        "data": data,
        "from": _sender(user_id),
        "message": bot_message,
    }
    return _update(bot, update_id, callback_query=query)


def inaccessible_callback_update(
    bot: Bot, data: str, *, user_id: int = 1001, update_id: int = 6
) -> Update:
    """A button press on a message Telegram no longer gives access to (date 0)."""
    query = {
        "id": f"old{update_id}",
        "chat_instance": "ci",
        "data": data,
        "from": _sender(user_id),
        "message": {
            "message_id": 5,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
        },
    }
    return _update(bot, update_id, callback_query=query)


def document_update(
    bot: Bot,
    *,
    file_name: str = "lecture.pdf",
    file_size: int = 1000,
    user_id: int = 2002,
    update_id: int = 3,
) -> Update:
    """A message with a document."""
    document = {
        "file_id": "doc-file-id",
        "file_unique_id": "doc-unique",
        "file_name": file_name,
        "file_size": file_size,
    }
    message = _message(user_id, update_id, document=document)
    return _update(bot, update_id, message=message)


def voice_update(bot: Bot, *, user_id: int = 2002, update_id: int = 4) -> Update:
    """A voice message."""
    voice = {"file_id": "voice-id", "file_unique_id": "voice-u", "duration": 3}
    return _update(bot, update_id, message=_message(user_id, update_id, voice=voice))


def blocked_update(bot: Bot, *, new_status: str, user_id: int = 1001) -> Update:
    """A my_chat_member update: the user blocked (kicked) or unblocked (member)."""
    member: dict[str, Any] = {
        "user": {"id": BOT_ID, "is_bot": True, "first_name": "Bot"}
    }
    new_member = {**member, "status": new_status}
    if new_status == "kicked":
        new_member["until_date"] = 0  # forever
    event = {
        "chat": {"id": user_id, "type": "private"},
        "from": _sender(user_id),
        "date": int(NOW.timestamp()),
        "old_chat_member": {**member, "status": "member"},
        "new_chat_member": new_member,
    }
    return _update(bot, 5, my_chat_member=event)
