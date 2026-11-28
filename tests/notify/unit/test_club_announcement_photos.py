"""Club announcement photos: renderer and dispatcher delivery shapes."""

from typing import Any
from uuid import UUID

from app.modules.notify.application.dispatch_due import DispatchDue
from app.modules.notify.application.renderers.clubs import ClubAnnouncementRenderer
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.base_error import BaseError
from app.shared.contracts.notify import PhotoRef, RenderContext, SentPhoto
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType
from tests.bot.support.fakes import make_user as make_bot_user
from tests.factories.notify import make_notification, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.limiter import CountingLimiter
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.notify.uow import InMemoryNotificationRepository


class PhotoSender(FakeTelegramSender):
    """Records photo and album calls in order, with the plain ones."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_message(
        self, chat_id: int, text_html: str, buttons: Any = None
    ) -> int:
        self.calls.append(("message", {"text": text_html, "buttons": buttons}))
        return await super().send_message(chat_id, text_html, buttons)

    async def send_photo(
        self,
        chat_id: int,
        photo: PhotoRef,
        caption_html: str | None = None,
        buttons: Any = None,
    ) -> SentPhoto:
        self.calls.append(
            ("photo", {"caption": caption_html, "buttons": buttons, "photo": photo})
        )
        return SentPhoto(message_id=1, file_id=f"tg-{photo.cache_key}")

    async def send_media_group(self, chat_id: int, photos: Any) -> list[SentPhoto]:
        self.calls.append(("group", {"photos": list(photos)}))
        return [SentPhoto(message_id=1, file_id="x") for _ in photos]

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


class BrokenFiles(FakeFilesApi):
    """Fails to read one file."""

    def __init__(self, bad: UUID | None = None) -> None:
        super().__init__()
        self.bad = bad

    async def read_bytes(self, file_id: UUID) -> bytes:
        if file_id == self.bad:
            raise BaseError()
        return await super().read_bytes(file_id)


BUTTON = {"text": "Open clubs", "web_app_url": "x"}


async def _run(
    i18n: I18nCore, files: FakeFilesApi, ids: list[UUID], text: str
) -> PhotoSender:
    sender = PhotoSender()
    repo = InMemoryNotificationRepository()
    identity = FakeIdentityDirectory()
    user = identity.add_user(make_user(), 11, 12)
    registry = RendererRegistry()
    registry.register(
        NotificationType.CLUB_ANNOUNCEMENT,
        ClubAnnouncementRenderer(i18n, UrlsSettings(), files),
    )
    repo.add(
        make_notification(
            user.id,
            NotificationType.CLUB_ANNOUNCEMENT,
            payload={
                "club_id": "c1",
                "text": text,
                "photo_file_ids": [str(i) for i in ids],
            },
        )
    )
    dispatch = DispatchDue(
        uow_factory=repo.uow,
        identity=identity,
        renderers=registry,
        sender=sender,
        limiter=CountingLimiter(),
        clock=FixedClock(),
    )
    await dispatch.execute()
    return sender


def _files(count: int) -> tuple[FakeFilesApi, list[UUID]]:
    files = FakeFilesApi()
    return files, [files.add(f"p{i}.jpg", b"jpg%d" % i).id for i in range(count)]


async def test_one_photo_short_text_is_one_photo_with_caption_and_button(
    i18n: I18nCore,
) -> None:
    files, ids = _files(1)

    sender = await _run(i18n, files, ids, "Training moved")

    assert sender.kinds() == ["photo", "photo"]  # two Telegram accounts
    first = sender.calls[0][1]
    assert "Training moved" in first["caption"] and first["buttons"]
    assert first["photo"].data == b"jpg0"


async def test_one_photo_long_text_is_photo_then_text(i18n: I18nCore) -> None:
    files, ids = _files(1)

    sender = await _run(i18n, files, ids, "x" * 1100)

    assert sender.kinds()[:2] == ["photo", "message"]
    assert sender.calls[0][1]["caption"] is None
    assert sender.calls[1][1]["buttons"]


async def test_three_photos_are_one_album_then_text_with_button(
    i18n: I18nCore,
) -> None:
    files, ids = _files(3)

    sender = await _run(i18n, files, ids, "Photos")

    assert sender.kinds()[:2] == ["group", "message"]
    assert len(sender.calls[0][1]["photos"]) == 3
    assert sender.calls[1][1]["buttons"]


async def test_unreadable_photo_is_skipped(i18n: I18nCore) -> None:
    files, ids = _files(2)
    broken = BrokenFiles(bad=ids[0])
    broken.refs, broken.blobs = files.refs, files.blobs

    sender = await _run(i18n, broken, ids, "Photos")

    assert sender.kinds()[0] == "photo"
    assert sender.calls[0][1]["photo"].data == b"jpg1"


async def test_no_readable_photo_sends_plain_text(i18n: I18nCore) -> None:
    files, ids = _files(1)
    broken = BrokenFiles(bad=ids[0])
    broken.refs, broken.blobs = files.refs, files.blobs

    sender = await _run(i18n, broken, ids, "Photos")

    assert sender.kinds()[0] == "message"


async def test_renderer_caps_at_ten_photos(i18n: I18nCore) -> None:
    files, ids = _files(12)
    renderer = ClubAnnouncementRenderer(i18n, UrlsSettings(), files)
    ctx = RenderContext(
        user=make_bot_user(Role.STUDENT), locale="en", telegram_user_id=1
    )

    message = await renderer({"club_id": "c", "text": "t", "photo_file_ids": ids}, ctx)

    assert message is not None and len(message.photos) == 10
    assert message.photos[0].cache_key == str(ids[0])
