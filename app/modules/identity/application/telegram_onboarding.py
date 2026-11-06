"""The mandatory Telegram step of registration: a one-time code or verified initData.

A registration outside Telegram gets a one-time code for a ``/start link_<code>`` deep
link; the page polls its state. A registration inside the mini app sends its signed
initData instead and is linked at once. Only the hash of the code is stored.
"""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.modules.identity.application.link_telegram_account import LinkTelegramAccount
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import TelegramLinkedElsewhereError
from app.modules.identity.ports.init_data_verifier import (
    InitDataUser,
    InitDataVerifier,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.base_error import UnauthorizedError

from pydantic import BaseModel

DEEP_LINK_PREFIX = "link_"
LINK_CODE_TTL = timedelta(minutes=30)
_BOT_CONTEXT = RequestContext(user_agent="telegram-bot")


class OnboardingLink(BaseModel):
    """The state behind one link code."""

    user_id: UUID
    linked: bool = False


class OnboardingLinkStore(Protocol):
    """Short-lived link codes keyed by their hash."""

    async def create(self, value: OnboardingLink) -> str:
        """Store the state and return the new code."""
        ...

    async def get(self, token: str) -> OnboardingLink | None:
        """Load the state; None if the code expired or never existed."""
        ...

    async def save(self, token: str, value: OnboardingLink) -> None:
        """Overwrite the state, keeping the remaining lifetime."""
        ...


class LinkOutcome(StrEnum):
    """What the bot tells the person who opened the deep link."""

    LINKED = "linked"
    EXPIRED = "expired"
    LINKED_ELSEWHERE = "linked_elsewhere"


@dataclass(frozen=True, slots=True)
class TelegramOnboarding:
    """Issue link codes, redeem them in the bot, link from mini app initData."""

    store: OnboardingLinkStore
    uow_factory: UowFactory
    linker: LinkTelegramAccount
    verifier: InitDataVerifier
    max_age: timedelta

    async def issue(self, user_id: UUID) -> str:
        """Return a new one-time code for this account."""
        return await self.store.create(OnboardingLink(user_id=user_id))

    async def is_linked(self, code: str) -> bool:
        """Return True once the code was redeemed; unknown codes are simply False."""
        state = await self.store.get(code)
        return state is not None and state.linked

    async def redeem(self, code: str, telegram_user: InitDataUser) -> LinkOutcome:
        """Link the Telegram account that opened the deep link; the code works once."""
        state = await self.store.get(code)
        if state is None or state.linked:
            return LinkOutcome.EXPIRED
        try:
            await self._link(state.user_id, telegram_user, _BOT_CONTEXT)
        except TelegramLinkedElsewhereError:
            return LinkOutcome.LINKED_ELSEWHERE
        await self.store.save(code, state.model_copy(update={"linked": True}))
        return LinkOutcome.LINKED

    async def link_from_init_data(
        self, user_id: UUID, raw_init_data: str, ctx: RequestContext
    ) -> bool:
        """Link the mini app account; False sends the user to the deep link."""
        try:
            telegram_user = self.verifier.verify(raw_init_data, max_age=self.max_age)
            await self._link(user_id, telegram_user, ctx)
        except (UnauthorizedError, TelegramLinkedElsewhereError):
            return False
        return True

    async def _link(
        self, user_id: UUID, telegram_user: InitDataUser, ctx: RequestContext
    ) -> None:
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            await self.linker.execute(uow, user, telegram_user, ctx)
            await uow.commit()
