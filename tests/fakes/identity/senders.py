"""Recording senders for one-time codes, emails and Telegram messages."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.ports.otp_sender import OtpContext
from app.shared.contracts.identity import UserRef


@dataclass(frozen=True)
class SentCode:
    """One delivered one-time code."""

    user_id: Any
    code: str
    purpose: str
    channels: tuple[str, ...]
    context: OtpContext | None


class FakeOtpSender:
    """Implements OtpSender; `codes` lists everything sent, in order."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.codes: list[SentCode] = []

    async def send_code(
        self,
        user: UserRef,
        code: str,
        *,
        purpose: str,
        channels: Sequence[str],
        context: OtpContext | None = None,
    ) -> None:
        """Record the code."""
        self.codes.append(SentCode(user.id, code, purpose, tuple(channels), context))

    def last(self, purpose: str | None = None) -> SentCode:
        """The latest code (optionally of one purpose)."""
        matching = [c for c in self.codes if purpose in (None, c.purpose)]
        return matching[-1]

    def count(self, purpose: str | None = None) -> int:
        """How many codes were sent."""
        return len([c for c in self.codes if purpose in (None, c.purpose)])


class FakeEmailSender:
    """Implements EmailSender; set `fail` to simulate a broken relay."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.sent: list[tuple[str, str, dict[str, Any], str]] = []
        self.fail = False

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Record the email or fail."""
        if self.fail:
            raise EmailDeliveryError(support_details="fake relay is down")
        self.sent.append((to, template, params, locale))

    def to(self, address: str, template: str | None = None) -> list[dict[str, Any]]:
        """Params of the emails sent to an address."""
        return [
            params
            for to, name, params, _ in self.sent
            if to == address and template in (None, name)
        ]

    def last_code(self, address: str) -> str:
        """The latest OTP code emailed to an address."""
        return str(self.to(address, "otp")[-1]["code"])


class FakeTelegramSender:
    """Implements TelegramSender; records messages, can fail for some chats."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.messages: list[tuple[int, str, list[list[dict[str, Any]]] | None]] = []
        self.failing: set[int] = set()
        self._next_id = 100

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Record the message; raise for chats in `failing`."""
        if chat_id in self.failing:
            raise RuntimeError("bot was blocked by the user")
        self.messages.append((chat_id, text_html, buttons))
        self._next_id += 1
        return self._next_id

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Not used by identity."""
        raise NotImplementedError

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Not used by identity."""
        raise NotImplementedError
