"""Course broadcasts: the enrolled students get a notification, the history keeps it."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.notify.application.course_broadcast import CourseBroadcastService
from app.modules.notify.application.describe import describe
from app.modules.notify.domain.course_broadcast import CourseBroadcastInvalidError
from app.settings import UrlsSettings
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.fakes.clock import FixedClock
from tests.fakes.notify.uow import (
    FakeNotifyUnitOfWork,
    InMemoryCourseBroadcasts,
    InMemoryNotificationRepository,
)

import pytest

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


class _World:
    def __init__(self) -> None:
        self.repository = InMemoryNotificationRepository()
        self.history = InMemoryCourseBroadcasts()
        self.outbox: list = []
        self.units: list[FakeNotifyUnitOfWork] = []
        self.clock = FixedClock(NOW)
        self.service = CourseBroadcastService(uow_factory=self._unit, clock=self.clock)

    def _unit(self) -> FakeNotifyUnitOfWork:
        unit = FakeNotifyUnitOfWork(self.repository, self.history, self.outbox)
        self.units.append(unit)
        return unit


@pytest.fixture
def world() -> _World:
    return _World()


async def test_broadcast_reaches_enrolled_only(world: _World) -> None:
    """Only the given enrolled students are notified, once each, never the author."""
    course, author = new_id(), new_id()
    enrolled = [new_id(), new_id(), new_id()]

    sent = await world.service.send(
        course_id=course,
        course_slug="algebra",
        author_id=author,
        title="Update",
        body="The exam moves to <Friday> & more",
        recipient_ids=[*enrolled, enrolled[0], author],
    )

    assert set(sent.user_ids) == set(enrolled)
    assert {d.user_id for d in world.outbox} == set(enrolled)
    assert len(world.outbox) == 3
    stranger = new_id()
    assert stranger not in {d.user_id for d in world.outbox}
    draft = world.outbox[0]
    assert draft.type is NotificationType.BROADCAST
    assert draft.payload["course_id"] == str(course)
    assert draft.payload["text"] == "The exam moves to &lt;Friday&gt; &amp; more"
    assert len({d.dedupe_key for d in world.outbox}) == 3
    assert world.units[0].commits == 1


async def test_the_notification_opens_the_course_in_the_lms(
    world: _World, i18n: I18nCore
) -> None:
    """The web description (also used for Web Push) links to the course page."""
    await world.service.send(
        course_id=new_id(),
        course_slug="algebra-9",
        author_id=new_id(),
        title="Update",
        body="Read chapter 2",
        recipient_ids=[new_id()],
    )

    description = describe(
        NotificationType.BROADCAST,
        world.outbox[0].payload,
        "en",
        i18n=i18n,
        urls=UrlsSettings(lms="https://lms.test"),
    )

    assert description.title == "Update"
    assert description.body == "Read chapter 2"
    assert description.link == "https://lms.test/course/?slug=algebra-9"


async def test_history_lists_the_newest_first_per_course(world: _World) -> None:
    """The history of a course holds only its own broadcasts, newest first."""
    course, other = new_id(), new_id()
    for course_id, title in (
        (course, "first"),
        (other, "elsewhere"),
        (course, "second"),
    ):
        await world.service.send(
            course_id=course_id,
            course_slug="c",
            author_id=new_id(),
            title=title,
            body="text",
            recipient_ids=[],
        )
        world.clock.advance(minutes=1)

    assert [b.title for b in await world.service.history(course)] == ["second", "first"]


@pytest.mark.parametrize(
    ("title", "body"),
    [("", "text"), ("  ", "text"), ("t", ""), ("x" * 121, "t"), ("t", "y" * 2001)],
)
async def test_empty_or_too_long_texts_are_refused(
    world: _World, title: str, body: str
) -> None:
    """A broadcast needs a title up to 120 and a text up to 2000 characters."""
    with pytest.raises(CourseBroadcastInvalidError):
        await world.service.send(
            course_id=UUID(int=1),
            course_slug="c",
            author_id=new_id(),
            title=title,
            body=body,
            recipient_ids=[new_id()],
        )
    assert world.outbox == []
