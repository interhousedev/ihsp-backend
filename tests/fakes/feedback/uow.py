"""In-memory unit of work, people, files and mailer of the feedback module."""

import copy
from collections.abc import Callable, Sequence
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.feedback.domain.feedback import (
    Feedback,
    FeedbackResponse,
    FeedbackStatus,
)
from app.modules.feedback.ports.feedback_repository import FeedbackFilter, PageAfter
from app.modules.feedback.ports.people import Person
from app.shared.contracts.files import FileRef
from app.shared.notifications import NotificationDraft


class FakeFeedbackStore:
    """The "database": items, responses and the committed notifications."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: dict[UUID, Feedback] = {}
        self.responses: list[FeedbackResponse] = []
        self.notifications: list[NotificationDraft] = []
        self.commits = 0


class FakeFeedbackRepository:
    """Items and responses of a FakeFeedbackStore."""

    def __init__(self, store: FakeFeedbackStore) -> None:
        """Bind to the store."""
        self.store = store

    def _counted(self, item: Feedback) -> Feedback:
        found = copy.deepcopy(item)
        found.response_count = sum(
            1 for r in self.store.responses if r.feedback_id == item.id
        )
        return found

    def _sorted(self, items: list[Feedback]) -> list[Feedback]:
        items.sort(key=lambda i: (i.created_at, i.id), reverse=True)
        return [self._counted(i) for i in items]

    async def add(self, item: Feedback) -> None:
        """Insert an item."""
        self.store.items[item.id] = copy.deepcopy(item)

    async def get(self, feedback_id: UUID) -> Feedback | None:
        """Return the item or None."""
        found = self.store.items.get(feedback_id)
        return self._counted(found) if found else None

    async def set_status(
        self, feedback_id: UUID, status: FeedbackStatus, now: datetime
    ) -> None:
        """Change the status."""
        self.store.items[feedback_id].status = status
        self.store.items[feedback_id].updated_at = now

    async def list_for_reporter(self, reporter_id: UUID) -> list[Feedback]:
        """The reporter's items, newest first."""
        return self._sorted(
            [i for i in self.store.items.values() if i.reporter_id == reporter_id]
        )

    async def list_page(
        self, flt: FeedbackFilter, after: PageAfter | None, limit: int
    ) -> list[Feedback]:
        """Filtered items, newest first, after the position."""
        items = [
            i
            for i in self.store.items.values()
            if (flt.status is None or i.status == flt.status)
            and (flt.kind is None or i.kind == flt.kind)
            and (flt.area is None or i.area == flt.area)
            and (after is None or (i.created_at, i.id) < (after.created_at, after.id))
        ]
        return self._sorted(items)[:limit]

    async def add_response(self, response: FeedbackResponse) -> None:
        """Insert a response."""
        self.store.responses.append(copy.deepcopy(response))

    async def responses(self, feedback_id: UUID) -> list[FeedbackResponse]:
        """Responses of an item, oldest first."""
        return [
            copy.deepcopy(r)
            for r in self.store.responses
            if r.feedback_id == feedback_id
        ]


class FakeFeedbackUnitOfWork:
    """Writes at once; notifications are kept until commit."""

    def __init__(self, store: FakeFeedbackStore) -> None:
        """Bind to the store."""
        self.store = store
        self.feedback = FakeFeedbackRepository(store)
        self._outbox: list[NotificationDraft] = []

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._outbox.extend(drafts)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Drop uncommitted notifications."""
        self._outbox = []

    async def commit(self) -> None:
        """Publish the notifications and count."""
        self.store.notifications.extend(self._outbox)
        self._outbox = []
        self.store.commits += 1


def fake_uow_factory(
    store: FakeFeedbackStore,
) -> Callable[[], FakeFeedbackUnitOfWork]:
    """A factory of units of work over the store."""
    return lambda: FakeFeedbackUnitOfWork(store)


class FakeFeedbackFiles:
    """The part of FilesApi feedback uses."""

    def __init__(self) -> None:
        """No files yet."""
        self.files: dict[UUID, FileRef] = {}

    async def get_many(self, file_ids: Sequence[UUID]) -> dict[UUID, FileRef]:
        """Return the existing files."""
        return {i: self.files[i] for i in file_ids if i in self.files}

    async def download_url(
        self,
        file_id: UUID,
        *,
        inline: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """A fake presigned URL."""
        return f"https://s3.test/{file_id}?ttl={ttl_seconds}"


class FakePeople:
    """PeopleDirectory over a dict."""

    def __init__(self) -> None:
        """Nobody yet."""
        self.persons: dict[UUID, Person] = {}
        self.admins: list[UUID] = []

    async def person(self, user_id: UUID) -> Person | None:
        """Return the person or None."""
        return self.persons.get(user_id)

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """Return the known persons."""
        return {i: self.persons[i] for i in user_ids if i in self.persons}

    async def admin_ids(self) -> list[UUID]:
        """Return the administrators."""
        return list(self.admins)


class FakeMailer:
    """Records mails; ``fail`` makes every send raise."""

    def __init__(self) -> None:
        """Nothing sent."""
        self.sent: list[dict[str, object]] = []
        self.fail = False

    async def send(
        self, *, sender_id: UUID, to_login: str, subject: str, html: str
    ) -> None:
        """Record or fail."""
        if self.fail:
            raise RuntimeError("mailbox suspended")
        self.sent.append(
            {"sender_id": sender_id, "to": to_login, "subject": subject, "html": html}
        )
