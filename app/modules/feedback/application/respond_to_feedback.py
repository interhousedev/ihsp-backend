"""An administrator answers a feedback item by Telegram and/or mail."""

import html
from collections.abc import Sequence
from uuid import UUID

from app.modules.feedback.application.views import FeedbackPresenter, ResponseView
from app.modules.feedback.domain.attachments import check_attachments
from app.modules.feedback.domain.errors import (
    FeedbackInvalidError,
    FeedbackNotFoundError,
)
from app.modules.feedback.domain.feedback import (
    Delivery,
    DeliveryStatus,
    Feedback,
    FeedbackResponse,
    ResponseChannel,
    normalize_response,
    parse_enum,
    unique_ids,
)
from app.modules.feedback.ports.people import FeedbackMailer, PeopleDirectory, Person
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FileRef, FilesApi
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)


class RespondToFeedback:
    """Store the response; a channel the reporter lacks is ``unavailable``."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        people: PeopleDirectory,
        mailer: FeedbackMailer | None,
        presenter: FeedbackPresenter,
        i18n: I18nCore,
        clock: Clock,
    ) -> None:
        """Store the dependencies; without a mailer mail is ``unavailable``."""
        self._uow_factory = uow_factory
        self._files = files
        self._people = people
        self._mailer = mailer
        self._presenter = presenter
        self._i18n = i18n
        self._clock = clock

    async def execute(
        self,
        actor: Actor,
        feedback_id: UUID,
        *,
        text: str,
        channels: Sequence[ResponseChannel | str],
        attachment_file_ids: Sequence[UUID] = (),
    ) -> ResponseView:
        """Answer the item.

        Raises:
            FeedbackInvalidError: Empty or too long text, no or unknown channel.
            FeedbackAttachmentError: A file is not the admin's, not ready, etc.
            FeedbackNotFoundError: No such item.
        """
        clean = normalize_response(text)
        chosen = _channels(channels)
        file_ids = unique_ids(tuple(attachment_file_ids))
        found = await self._files.get_many(file_ids) if file_ids else {}
        check_attachments(file_ids, found, actor.user_id)
        async with self._uow_factory() as uow:
            item = await uow.feedback.get(feedback_id)
        if item is None:
            raise FeedbackNotFoundError()
        reporter = await self._people.person(item.reporter_id)
        refs = [found[file_id] for file_id in file_ids]
        response = FeedbackResponse(
            id=new_id(),
            feedback_id=item.id,
            author_id=actor.user_id,
            text=clean,
            channels=chosen,
            deliveries=[],
            created_at=self._clock.now(),
            attachment_file_ids=file_ids,
        )
        telegram = ResponseChannel.TELEGRAM in chosen and _has_telegram(reporter)
        response.deliveries = await self._deliveries(
            chosen, telegram, item, response, reporter, refs
        )
        async with self._uow_factory() as uow:
            await uow.feedback.add_response(response)
            if telegram:
                uow.notify(_telegram_draft(item, response, refs))
            await uow.commit()
        author = await self._people.people([actor.user_id])
        return await self._presenter.response(response, author)

    async def _deliveries(
        self,
        chosen: list[ResponseChannel],
        telegram: bool,
        item: Feedback,
        response: FeedbackResponse,
        reporter: Person | None,
        refs: list[FileRef],
    ) -> list[Delivery]:
        deliveries: list[Delivery] = []
        for channel in chosen:
            if channel == ResponseChannel.TELEGRAM:
                status = DeliveryStatus.SENT if telegram else DeliveryStatus.UNAVAILABLE
            else:
                status = await self._mail(item, response, reporter, refs)
            deliveries.append(Delivery(channel, status))
        return deliveries

    async def _mail(
        self,
        item: Feedback,
        response: FeedbackResponse,
        reporter: Person | None,
        refs: list[FileRef],
    ) -> DeliveryStatus:
        if self._mailer is None or reporter is None or not reporter.login:
            return DeliveryStatus.UNAVAILABLE
        t = self._i18n.get_context(reporter.locale)
        names = "".join(f"<li>{html.escape(ref.name)}</li>" for ref in refs)
        body = "<br>".join(html.escape(line) for line in response.text.splitlines())
        page = t("feedback-mail-body", title=html.escape(item.title), text=body)
        if names:
            label = html.escape(t("feedback-mail-attachments"))
            page += f"<p>{label}</p><ul>{names}</ul>"
        try:
            await self._mailer.send(
                sender_id=response.author_id,
                to_login=reporter.login,
                subject=t("feedback-mail-subject", title=item.title),
                html=page,
            )
        except Exception as exc:  # noqa: BLE001  any mail failure is a failed delivery
            log.warning("feedback_mail_failed", error_type=type(exc).__name__)
            return DeliveryStatus.FAILED
        return DeliveryStatus.SENT


def _channels(channels: Sequence[ResponseChannel | str]) -> list[ResponseChannel]:
    chosen = list(
        dict.fromkeys(parse_enum(ResponseChannel, c, "channels") for c in channels)
    )
    if not chosen:
        raise FeedbackInvalidError(params={"field": "channels"})
    return chosen


def _has_telegram(reporter: Person | None) -> bool:
    return reporter is not None and reporter.has_telegram


def _telegram_draft(
    item: Feedback, response: FeedbackResponse, refs: list[FileRef]
) -> NotificationDraft:
    """The FEEDBACK_RESPONSE notification; the bot sends the files as documents."""
    return NotificationDraft(
        user_id=item.reporter_id,
        type=NotificationType.FEEDBACK_RESPONSE,
        payload={
            "feedback_id": str(item.id),
            "response_id": str(response.id),
            "title": item.title,
            "text": response.text,
            "attachments": [
                {
                    "file_id": str(ref.id),
                    "name": ref.name,
                    "mime": ref.content_type,
                    "size": ref.byte_size,
                }
                for ref in refs
            ],
        },
        dedupe_key=f"feedback-response:{response.id}",
    )
