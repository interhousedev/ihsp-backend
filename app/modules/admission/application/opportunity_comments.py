"""Comments under opportunities: posting, moderation and reports."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import OpportunityService
from app.modules.admission.domain import opportunity_comments as oc
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    InvalidTransitionError,
)
from app.modules.admission.domain.opportunity_comments import (
    OppComment,
    OppCommentReport,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

REPORTS_PATH = "/staff/opportunities/reports/"


@dataclass(frozen=True, slots=True)
class CommentView:
    """A comment with its author's display name."""

    comment: OppComment
    author_name: str


@dataclass(frozen=True, slots=True)
class ReportView:
    """A queued report with the reported comment."""

    report: OppCommentReport
    comment: OppComment
    reporter_name: str
    author_name: str


class OppCommentService:
    """Comments are published at once; staff hide, authors delete, users report."""

    def __init__(
        self,
        uow_factory: UowFactory,
        opportunities: OpportunityService,
        clock: Clock,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._opps = opportunities
        self._clock = clock
        self._identity = identity

    def _require_moderator(self, ctx: AdmissionContext) -> None:
        if not self._opps.can_moderate(ctx):
            raise AdmissionForbiddenError(
                params={"permission": "opportunities:moderate"}
            )

    async def _names(self, ids: set[UUID]) -> dict[UUID, str]:
        if self._identity is None or not ids:
            return {}
        users = await self._identity.get_users(list(ids))
        return {i: f"{u.last_name} {u.first_name}".strip() for i, u in users.items()}

    async def list(
        self, ctx: AdmissionContext, opportunity_id: UUID
    ) -> list[CommentView]:
        """Published comments; hidden ones are shown to moderators only."""
        moderator = self._opps.can_moderate(ctx)
        async with self._uow() as uow:
            comments = await uow.opp_comments.list_for(
                opportunity_id, include_hidden=moderator
            )
        names = await self._names({c.author_id for c in comments})
        return [CommentView(c, names.get(c.author_id, "")) for c in comments]

    async def counts(self, opportunity_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Published comment counts per entry."""
        async with self._uow() as uow:
            return await uow.opp_comments.counts(opportunity_ids)

    async def post(
        self, ctx: AdmissionContext, opportunity_id: UUID, body: str
    ) -> CommentView:
        """Publish a comment immediately."""
        if oc.body_problem(body):
            raise CharLimitError(params={"field": "body", "limit": oc.BODY_MAX})
        comment = OppComment(
            id=new_id(),
            opportunity_id=opportunity_id,
            author_id=ctx.user_id,
            body=body.strip(),
            created_at=self._clock.now(),
        )
        async with self._uow() as uow:
            if await uow.opportunities.get(opportunity_id) is None:
                raise AdmissionNotFoundError()
            saved = await uow.opp_comments.add(comment)
            await uow.commit()
        names = await self._names({ctx.user_id})
        return CommentView(saved, names.get(ctx.user_id, ""))

    async def delete(self, ctx: AdmissionContext, comment_id: UUID) -> None:
        """The author deletes their comment."""
        async with self._uow() as uow:
            comment = await uow.opp_comments.get(comment_id)
            if comment is None or comment.status == "deleted":
                raise AdmissionNotFoundError()
            if comment.author_id != ctx.user_id:
                raise AdmissionForbiddenError(params={"permission": "owner"})
            await uow.opp_comments.save(oc.delete(comment, self._clock.now()))
            await uow.commit()

    async def hide(self, ctx: AdmissionContext, comment_id: UUID) -> OppComment:
        """Staff hide a comment; its open reports are resolved."""
        self._require_moderator(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            comment = await self._get(uow, comment_id)
            saved = await uow.opp_comments.save(oc.hide(comment, ctx.user_id, now))
            for report in await uow.opp_comments.reports_of(comment_id):
                await uow.opp_comments.save_report(
                    oc.close_report(report, "resolved", ctx.user_id, now)
                )
            await uow.commit()
        return saved

    async def unhide(self, ctx: AdmissionContext, comment_id: UUID) -> OppComment:
        """Staff restore a hidden comment."""
        self._require_moderator(ctx)
        async with self._uow() as uow:
            comment = await self._get(uow, comment_id)
            saved = await uow.opp_comments.save(oc.unhide(comment))
            await uow.commit()
        return saved

    @staticmethod
    async def _get(uow: object, comment_id: UUID) -> OppComment:
        repo: Any = uow.opp_comments  # type: ignore[attr-defined]
        comment: OppComment | None = await repo.get(comment_id)
        if comment is None or comment.status == "deleted":
            raise AdmissionNotFoundError()
        return comment

    async def report(
        self, ctx: AdmissionContext, comment_id: UUID, reason: str
    ) -> None:
        """File a report and tell the administrators."""
        text = reason.strip()
        if not text or len(text) > oc.REASON_MAX:
            raise CharLimitError(params={"field": "reason", "limit": oc.REASON_MAX})
        report = OppCommentReport(
            id=new_id(),
            comment_id=comment_id,
            reporter_id=ctx.user_id,
            reason=text,
            created_at=self._clock.now(),
        )
        async with self._uow() as uow:
            comment = await uow.opp_comments.get(comment_id)
            if comment is None or comment.status == "deleted":
                raise AdmissionNotFoundError()
            if not oc.may_report(comment, ctx.user_id):
                raise InvalidTransitionError(params={"status": comment.status})
            if not await uow.opp_comments.add_report(report):
                return
            if self._identity is not None:
                name = (await self._names({ctx.user_id})).get(ctx.user_id, "")
                for admin_id in await self._identity.user_ids_with_roles([Role.ADMIN]):
                    uow.notify(
                        NotificationDraft(
                            user_id=admin_id,
                            type=NotificationType.ADMISSION_COMMENT_ADDED,
                            payload={
                                "kind": "opportunity_report",
                                "author_name": name,
                                "path": REPORTS_PATH,
                            },
                            dedupe_key=f"oppreport:{report.id}",
                        )
                    )
            await uow.commit()

    async def reports(self, ctx: AdmissionContext) -> Sequence[ReportView]:
        """The staff queue of open reports."""
        self._require_moderator(ctx)
        async with self._uow() as uow:
            reports = await uow.opp_comments.open_reports()
            comments: dict[UUID, OppComment] = {}
            for r in reports:
                found = await uow.opp_comments.get(r.comment_id)
                if found is not None:
                    comments[r.comment_id] = found
        ids = {r.reporter_id for r in reports} | {
            c.author_id for c in comments.values()
        }
        names = await self._names(ids)
        return [
            ReportView(
                r,
                comments[r.comment_id],
                names.get(r.reporter_id, ""),
                names.get(comments[r.comment_id].author_id, ""),
            )
            for r in reports
            if r.comment_id in comments
        ]

    async def dismiss(self, ctx: AdmissionContext, report_id: UUID) -> None:
        """Staff close a report without touching the comment."""
        self._require_moderator(ctx)
        async with self._uow() as uow:
            report = await uow.opp_comments.get_report(report_id)
            if report is None:
                raise AdmissionNotFoundError()
            await uow.opp_comments.save_report(
                oc.close_report(report, "dismissed", ctx.user_id, self._clock.now())
            )
            await uow.commit()
