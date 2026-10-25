"""Send feedback (any signed-in user, from the web or the bot)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.feedback.application.views import FeedbackPresenter, FeedbackView
from app.modules.feedback.domain.attachments import check_attachments
from app.modules.feedback.domain.errors import FeedbackRateLimitedError
from app.modules.feedback.domain.feedback import (
    DAILY_LIMIT,
    Feedback,
    FeedbackArea,
    FeedbackKind,
    FeedbackSource,
    FeedbackStatus,
    normalize_description,
    normalize_page_url,
    normalize_title,
    parse_enum,
    unique_ids,
)
from app.modules.feedback.ports.people import PeopleDirectory
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.rate_limit import RateLimiter

DAY_SECONDS = 86_400


class SubmitFeedback:
    """Validate, check attachments and the daily limit, store, tell the admins."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        people: PeopleDirectory,
        presenter: FeedbackPresenter,
        rate_limiter: RateLimiter,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files
        self._people = people
        self._presenter = presenter
        self._rate_limiter = rate_limiter
        self._clock = clock

    async def __call__(
        self,
        actor: Actor,
        kind: FeedbackKind | str,
        area: FeedbackArea | str,
        title: str,
        description: str,
        attachment_file_ids: Sequence[UUID] = (),
        source: FeedbackSource | str = FeedbackSource.WEB,
        page_url: str | None = None,
    ) -> FeedbackView:
        """Same as ``execute`` (the bot calls ``container.feedback.submit(...)``)."""
        return await self.execute(
            actor,
            kind=kind,
            area=area,
            title=title,
            description=description,
            attachment_file_ids=attachment_file_ids,
            source=source,
            page_url=page_url,
        )

    async def execute(
        self,
        actor: Actor,
        *,
        kind: FeedbackKind | str,
        area: FeedbackArea | str,
        title: str,
        description: str,
        attachment_file_ids: Sequence[UUID] = (),
        source: FeedbackSource | str = FeedbackSource.WEB,
        page_url: str | None = None,
    ) -> FeedbackView:
        """Create the feedback.

        Raises:
            FeedbackInvalidError: A field is empty, too long or not allowed.
            FeedbackAttachmentError: A file is missing, foreign, not ready or of a
                wrong type, or there are more than 10.
            FeedbackRateLimitedError: More than 10 items today (429).
        """
        now = self._clock.now()
        file_ids = unique_ids(tuple(attachment_file_ids))
        item = Feedback(
            id=new_id(),
            reporter_id=actor.user_id,
            kind=parse_enum(FeedbackKind, kind, "kind"),
            area=parse_enum(FeedbackArea, area, "area"),
            title=normalize_title(title),
            description=normalize_description(description),
            status=FeedbackStatus.NEW,
            source=parse_enum(FeedbackSource, source, "source"),
            created_at=now,
            updated_at=now,
            page_url=normalize_page_url(page_url),
            attachment_file_ids=file_ids,
        )
        found = await self._files.get_many(file_ids) if file_ids else {}
        check_attachments(file_ids, found, actor.user_id)
        try:
            await self._rate_limiter.hit(
                f"feedback:{actor.user_id}",
                limit=DAILY_LIMIT,
                window_seconds=DAY_SECONDS,
            )
        except RateLimitedError as exc:
            raise FeedbackRateLimitedError(params=exc.params) from exc
        await self._store(item)
        return (await self._presenter.items([item]))[0]

    async def _store(self, item: Feedback) -> None:
        reporter = await self._people.person(item.reporter_id)
        admins = await self._people.admin_ids()
        payload = {
            "feedback_id": str(item.id),
            "kind": item.kind.value,
            "area": item.area.value,
            "title": item.title,
            "reporter_name": reporter.display_name if reporter else "",
        }
        async with self._uow_factory() as uow:
            await uow.feedback.add(item)
            uow.notify(
                *(
                    NotificationDraft(
                        user_id=admin,
                        type=NotificationType.FEEDBACK_NEW,
                        payload=payload,
                        dedupe_key=f"feedback-new:{item.id}:{admin}",
                    )
                    for admin in admins
                    if admin != item.reporter_id
                )
            )
            await uow.commit()
