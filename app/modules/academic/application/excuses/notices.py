"""Notifications of excuses, written in the transaction of the change."""

from uuid import UUID

from app.modules.academic.application.excuses.ports import (
    DecisionTokens,
    ExcuseDirectory,
    ExcuseUnitOfWork,
    StudentContext,
)
from app.modules.academic.domain.excuses.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseTemplate,
)
from app.shared.notifications import NotificationDraft, NotificationType

PREVIEW_CHARS = 200


class ExcuseNotices:
    """Who is told what: the curator of requests, the student of decisions."""

    def __init__(self, *, directory: ExcuseDirectory, tokens: DecisionTokens) -> None:
        """Store the ports."""
        self.directory = directory
        self.tokens = tokens

    async def requested(
        self,
        uow: ExcuseUnitOfWork,
        excuse: Excuse,
        template: ExcuseTemplate,
        context: StudentContext,
        student_name: str,
    ) -> None:
        """Tell the curator (Administration when the group has none)."""
        recipients = (
            [context.curator_id]
            if context.curator_id is not None
            else await self.directory.admin_ids()
        )
        for user_id in recipients:
            approve, reject = await self.tokens.issue(excuse.id, user_id)
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.EXCUSE_REQUESTED,
                    payload={
                        "excuse_id": str(excuse.id),
                        "student_id": str(excuse.student_id),
                        "student_name": student_name,
                        "template_code": template.code,
                        "starts_on": excuse.starts_on.isoformat(),
                        "ends_on": (
                            excuse.ends_on.isoformat() if excuse.ends_on else None
                        ),
                        "approve_token": approve,
                        "reject_token": reject,
                    },
                    dedupe_key=f"excuse_requested:{excuse.id}:{user_id}",
                )
            )

    def decided(self, uow: ExcuseUnitOfWork, excuse: Excuse) -> None:
        """Tell the student how their excuse stands."""
        uow.notify(
            NotificationDraft(
                user_id=excuse.student_id,
                type=NotificationType.EXCUSE_DECIDED,
                payload={
                    "excuse_id": str(excuse.id),
                    "status": excuse.status.value,
                    "origin": excuse.origin.value,
                    "comment": excuse.decision_comment,
                    "starts_on": excuse.starts_on.isoformat(),
                },
                dedupe_key=f"excuse_decided:{excuse.id}:{excuse.version}",
            )
        )

    async def message(
        self,
        uow: ExcuseUnitOfWork,
        excuse: Excuse,
        message: ExcuseMessage,
        author_name: str,
    ) -> None:
        """Tell the other side: the curator when the student wrote, else the student."""
        recipients: list[UUID]
        if message.author_id == excuse.student_id:
            context = await self.directory.student_context(excuse.student_id)
            recipients = (
                [context.curator_id]
                if context is not None and context.curator_id is not None
                else await self.directory.admin_ids()
            )
        else:
            recipients = [excuse.student_id]
        preview = message.body[:PREVIEW_CHARS]
        for user_id in recipients:
            if user_id == message.author_id:
                continue
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.EXCUSE_MESSAGE,
                    payload={
                        "excuse_id": str(excuse.id),
                        "author_name": author_name,
                        "preview": preview,
                        "files": len(message.file_ids),
                    },
                    dedupe_key=f"excuse_message:{message.id}:{user_id}",
                )
            )
