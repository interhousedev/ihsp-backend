"""Deleting one user's notifications of given types (erasure from another app)."""

from app.modules.notify.application.public_api import NotifyApiImpl
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType
from tests.factories.notify import NOW, make_notification, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.uow import FakeNotifyUnitOfWork, InMemoryNotificationRepository


async def test_only_that_users_notifications_of_those_types_go(
    i18n: I18nCore,
) -> None:
    repo = InMemoryNotificationRepository()
    identity = FakeIdentityDirectory()
    me = identity.add_user(make_user(Role.STUDENT))
    other = identity.add_user(make_user(Role.STUDENT))
    api = NotifyApiImpl(
        uow_factory=lambda: FakeNotifyUnitOfWork(repo),
        identity=identity,
        i18n=i18n,
        urls=UrlsSettings(),
        clock=FixedClock(NOW),
    )
    gone = repo.add(make_notification(me.id, NotificationType.TRANSCRIPT_READY))
    kept_type = repo.add(make_notification(me.id, NotificationType.KNOWLEDGE_GAP))
    kept_other = repo.add(
        make_notification(other.id, NotificationType.TRANSCRIPT_READY)
    )

    removed = await api.delete_for_user(me.id, [NotificationType.TRANSCRIPT_READY])

    assert removed == 1
    assert set(repo.rows) == {kept_type.id, kept_other.id}
    assert gone.id not in repo.rows
