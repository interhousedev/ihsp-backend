"""AI-ACCESS: an administrator revokes and restores chat or notebook AI, audited."""

from datetime import date
from typing import Any, Self
from uuid import UUID

from app.modules.admin.application.limit_admin import (
    AUDIT_AI_ACCESS_CHANGED,
    LimitAdmin,
    LimitUserNotFoundError,
)
from app.settings import LimitsSettings
from app.shared.actor import Role
from app.shared.ai_access import AiAccess
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from app.shared.limits import EffectiveLimits, LimitSnapshot
from tests.factories import make_actor
from tests.factories.notify import make_user
from tests.fakes.notify.identity import FakeIdentityDirectory


class FakeLimitStore:
    def __init__(self) -> None:
        self.access: dict[UUID, AiAccess] = {}

    async def get_ai_access(self, user_id: UUID) -> AiAccess:
        return self.access.get(user_id, AiAccess())

    async def save_ai_access(
        self, user_id: UUID, access: AiAccess, *, actor_id: UUID
    ) -> None:
        self.access[user_id] = access


class FakeUow:
    def __init__(self, store: FakeLimitStore, audits: list[Any]) -> None:
        self.limit_store = store
        self._audits = audits
        self._drafts: list[Any] = []
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def audit(self, *drafts: Any) -> None:
        self._drafts.extend(drafts)

    async def commit(self) -> None:
        self._audits.extend(self._drafts)
        self.committed = True


def _admin(
    identity: FakeIdentityDirectory, store: FakeLimitStore, audits: list[Any]
) -> LimitAdmin:
    provider = EffectiveLimits(
        LimitsSettings(),
        lambda: _empty(),
        today=lambda: date(2026, 10, 25),
    )
    return LimitAdmin(
        uow_factory=lambda: FakeUow(store, audits),
        identity=identity,
        limits=provider,
        base=LimitsSettings(),
        today=lambda: date(2026, 10, 25),
    )


async def _empty() -> LimitSnapshot:
    return LimitSnapshot()


async def test_an_admin_revokes_chat_and_the_change_is_audited() -> None:
    identity = FakeIdentityDirectory()
    student_id = new_id()
    identity.add_user(make_user(Role.STUDENT, user_id=student_id), 901)
    store = FakeLimitStore()
    audits: list[Any] = []
    admin = _admin(identity, store, audits)
    actor = make_actor(Role.ADMIN)

    saved = await admin.set_ai_access(actor, student_id, AiAccess(chat_blocked=True))

    assert saved == AiAccess(chat_blocked=True)
    assert await admin.ai_access(actor, student_id) == AiAccess(chat_blocked=True)
    (draft,) = audits
    assert draft.type == AUDIT_AI_ACCESS_CHANGED
    assert draft.metadata["old"] == {
        "ai_chat_blocked": False,
        "ai_notebooks_blocked": False,
    }
    assert draft.metadata["new"] == {
        "ai_chat_blocked": True,
        "ai_notebooks_blocked": False,
    }


async def test_setting_the_same_flags_again_writes_no_audit_row() -> None:
    identity = FakeIdentityDirectory()
    student_id = new_id()
    identity.add_user(make_user(Role.STUDENT, user_id=student_id), 902)
    store = FakeLimitStore()
    audits: list[Any] = []
    admin = _admin(identity, store, audits)
    actor = make_actor(Role.ADMIN)

    await admin.set_ai_access(actor, student_id, AiAccess(notebooks_blocked=True))
    await admin.set_ai_access(actor, student_id, AiAccess(notebooks_blocked=True))

    assert len(audits) == 1


async def test_only_an_admin_may_change_the_revocation() -> None:
    identity = FakeIdentityDirectory()
    student_id = new_id()
    identity.add_user(make_user(Role.STUDENT, user_id=student_id), 903)
    admin = _admin(identity, FakeLimitStore(), [])

    try:
        await admin.set_ai_access(
            make_actor(Role.TEACHER), student_id, AiAccess(chat_blocked=True)
        )
    except ForbiddenError:
        return
    raise AssertionError("a teacher must not revoke AI access")


async def test_an_unknown_user_is_not_found() -> None:
    admin = _admin(FakeIdentityDirectory(), FakeLimitStore(), [])

    try:
        await admin.set_ai_access(
            make_actor(Role.ADMIN), new_id(), AiAccess(chat_blocked=True)
        )
    except LimitUserNotFoundError:
        return
    raise AssertionError("an unknown user must be refused")
