"""The registration's Telegram step: one-time codes and mini app initData."""

from datetime import timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from app.modules.identity.application import telegram_onboarding as module
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.telegram_onboarding import (
    LinkOutcome,
    OnboardingLink,
    TelegramOnboarding,
)
from app.modules.identity.domain.errors import TelegramLinkedElsewhereError
from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.shared.base_error import UnauthorizedError

import pytest

TG = InitDataUser(id=7, first_name="Ali")


class Store:
    def __init__(self) -> None:
        self.values: dict[str, OnboardingLink] = {}

    async def create(self, value: OnboardingLink) -> str:
        self.values["code"] = value
        return "code"

    async def get(self, token: str) -> OnboardingLink | None:
        return self.values.get(token)

    async def save(self, token: str, value: OnboardingLink) -> None:
        self.values[token] = value


class Uow:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


class Linker:
    def __init__(self) -> None:
        self.linked: list[tuple[UUID, int]] = []
        self.taken = False

    async def execute(
        self, uow: Uow, user: UUID, telegram_user: InitDataUser, ctx: RequestContext
    ) -> bool:
        if self.taken:
            raise TelegramLinkedElsewhereError()
        self.linked.append((user, telegram_user.id))
        return True


class Verifier:
    def verify(self, raw: str, *, max_age: timedelta) -> InitDataUser:
        if raw != "signed":
            raise UnauthorizedError()
        return TG


@pytest.fixture
def linker() -> Linker:
    return Linker()


@pytest.fixture
def service(linker: Linker, monkeypatch: pytest.MonkeyPatch) -> TelegramOnboarding:
    async def require_user(uow: Uow, user_id: UUID) -> UUID:
        return user_id

    monkeypatch.setattr(module, "require_user", require_user)
    return TelegramOnboarding(
        store=Store(),
        uow_factory=Uow,  # type: ignore[arg-type]
        linker=linker,  # type: ignore[arg-type]
        verifier=Verifier(),
        max_age=timedelta(hours=1),
    )


async def test_a_code_links_once_and_reports_the_state(
    service: TelegramOnboarding, linker: Linker
) -> None:
    user_id = uuid4()
    code = await service.issue(user_id)
    assert await service.is_linked(code) is False

    assert await service.redeem(code, TG) is LinkOutcome.LINKED
    assert await service.is_linked(code) is True
    assert linker.linked == [(user_id, TG.id)]

    other = InitDataUser(id=8, first_name="Eve")
    assert await service.redeem(code, other) is LinkOutcome.EXPIRED
    assert linker.linked == [(user_id, TG.id)]


async def test_an_unknown_code_links_nothing(
    service: TelegramOnboarding, linker: Linker
) -> None:
    assert await service.redeem("nope", TG) is LinkOutcome.EXPIRED
    assert await service.is_linked("nope") is False
    assert linker.linked == []


async def test_a_telegram_account_of_someone_else_leaves_the_code_usable(
    service: TelegramOnboarding, linker: Linker
) -> None:
    code = await service.issue(uuid4())
    linker.taken = True

    assert await service.redeem(code, TG) is LinkOutcome.LINKED_ELSEWHERE
    assert await service.is_linked(code) is False


async def test_signed_init_data_links_at_once(
    service: TelegramOnboarding, linker: Linker
) -> None:
    user_id = uuid4()

    assert await service.link_from_init_data(user_id, "signed", RequestContext())
    assert linker.linked == [(user_id, TG.id)]


async def test_forged_init_data_falls_back_to_the_deep_link(
    service: TelegramOnboarding, linker: Linker
) -> None:
    assert not await service.link_from_init_data(uuid4(), "forged", RequestContext())
    assert linker.linked == []
