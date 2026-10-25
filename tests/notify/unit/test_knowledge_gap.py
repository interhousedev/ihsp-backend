"""Knowledge gap alert for administrators with a 24 hour dedupe."""

from datetime import timedelta

from app.modules.notify.application.public_api import NotifyApiImpl
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationDraft, NotificationType
from tests.factories.notify import NOW, make_notification, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.uow import FakeNotifyUnitOfWork, InMemoryNotificationRepository


class World:
    def __init__(self, i18n: I18nCore) -> None:
        self.repo = InMemoryNotificationRepository()
        self.identity = FakeIdentityDirectory()
        self.admin = self.identity.add_user(make_user(Role.ADMIN))
        self.outbox: list[NotificationDraft] = []

        def factory() -> FakeNotifyUnitOfWork:
            return FakeNotifyUnitOfWork(self.repo, outbox=self.outbox)

        self.api = NotifyApiImpl(
            uow_factory=factory,
            identity=self.identity,
            i18n=i18n,
            urls=UrlsSettings(),
            clock=FixedClock(NOW),
        )


async def test_every_admin_gets_a_truncated_query(i18n: I18nCore) -> None:
    world = World(i18n)
    second = world.identity.add_user(make_user(Role.ADMIN))

    queued = await world.api.notify_knowledge_gap(
        query="x" * 400, chat_kind="student_chat", user_role="student"
    )

    assert queued == 2
    assert {d.user_id for d in world.outbox} == {world.admin.id, second.id}
    draft = world.outbox[0]
    assert draft.type == NotificationType.KNOWLEDGE_GAP
    assert draft.payload["query"] == "x" * 300
    assert draft.payload["chat_id"] is None


async def test_same_normalized_query_within_a_day_is_skipped(i18n: I18nCore) -> None:
    world = World(i18n)
    await world.api.notify_knowledge_gap(
        query="Dress  Code", chat_kind="admin_chat", user_role="admin"
    )
    key = world.outbox[0].dedupe_key
    world.repo.add(
        make_notification(
            world.admin.id,
            NotificationType.KNOWLEDGE_GAP,
            dedupe_key=key,
            created_at=NOW - timedelta(hours=23),
        )
    )
    world.outbox.clear()

    assert (
        await world.api.notify_knowledge_gap(
            query=" dress code ", chat_kind="admin_chat", user_role="admin"
        )
        == 0
    )
    assert world.outbox == []


async def test_after_a_day_the_query_is_announced_again(i18n: I18nCore) -> None:
    world = World(i18n)
    await world.api.notify_knowledge_gap(
        query="dress code", chat_kind="admin_chat", user_role="admin"
    )
    world.repo.add(
        make_notification(
            world.admin.id,
            NotificationType.KNOWLEDGE_GAP,
            dedupe_key=world.outbox[0].dedupe_key,
            created_at=NOW - timedelta(hours=25),
        )
    )
    world.outbox.clear()

    assert (
        await world.api.notify_knowledge_gap(
            query="dress code", chat_kind="admin_chat", user_role="admin"
        )
        == 1
    )
