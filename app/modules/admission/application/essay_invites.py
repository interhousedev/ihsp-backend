"""Use cases of essay review links: the student's side and the guest reviewer's."""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InviteLimitError,
    InviteNotFoundError,
)
from app.modules.admission.domain.essay_invites import (
    AUTHOR_MAX,
    BODY_MAX,
    COMMENTS_PER_HOUR,
    LABEL_MAX,
    MAX_ACTIVE_INVITES,
    OPENS_PER_HOUR,
    QUOTE_MAX,
    Anchor,
    Audience,
    EssayInvite,
    Feedback,
    check_text,
    check_ttl,
    new_token,
    reanchor,
    token_hash,
)
from app.modules.admission.domain.essays import Essay
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

HOUR: Final = 3600
"""Window of the guest rate limits, in seconds."""


@dataclass(frozen=True, slots=True)
class CreatedInvite:
    """A new link with its plain token, shown this once."""

    invite: EssayInvite
    token: str


@dataclass(frozen=True, slots=True)
class FeedbackView:
    """A comment placed in the current text, with the label of its link."""

    item: Feedback
    anchor: Anchor
    invite_label: str | None = None


@dataclass(frozen=True, slots=True)
class GuestView:
    """What a reviewer sees through a link: the essay and their own comments."""

    essay: Essay
    invite: EssayInvite
    feedback: list[FeedbackView]


@dataclass(frozen=True, slots=True)
class CommentDraft:
    """A comment as typed: the text and an optional quoted span."""

    body: str
    quote: str | None = None
    anchor_start: int | None = None
    anchor_end: int | None = None


def _ip_bucket(ip: str | None) -> str:
    """Return the rate-limit bucket of a client address (never the raw address)."""
    if not ip:
        return "unknown"
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _view(item: Feedback, text: str, label: str | None = None) -> FeedbackView:
    anchor = reanchor(text, item.quote, item.anchor_start, item.anchor_end)
    return FeedbackView(item, anchor, label)


def _placed(text: str, draft: CommentDraft) -> tuple[str | None, Anchor]:
    """Check the draft's lengths and place its quote in the current text."""
    quote = check_text("quote", draft.quote, QUOTE_MAX)
    anchor = reanchor(text, quote, draft.anchor_start, draft.anchor_end)
    if anchor.detached:
        raise ValidationFailedError(params={"field": "quote"})
    return quote, anchor


def _body(draft: CommentDraft) -> str:
    body = check_text("body", draft.body, BODY_MAX)
    if body is None:
        raise ValidationFailedError(params={"field": "body"})
    return body


class EssayInviteService:
    """Review links and feedback of one student's essays."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        rate_limiter: RateLimiter,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._rl = rate_limiter

    async def _own(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, essay_id: UUID
    ) -> Essay:
        """Return the caller's own essay; anyone else's answers 404."""
        essay = await uow.essays.get(essay_id)
        if essay is None:
            raise AdmissionNotFoundError()
        resolution = await self._access.resolve(ctx, essay.student_id)
        if not resolution.owner:
            raise AdmissionNotFoundError()
        return essay

    async def create(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        *,
        audience: Audience,
        label: str | None = None,
        can_comment: bool = True,
        ttl_days: int = 30,
    ) -> CreatedInvite:
        """Make a review link; at most MAX_ACTIVE_INVITES may be active."""
        ttl = check_ttl(ttl_days)
        clean_label = check_text("label", label, LABEL_MAX)
        now = self._clock.now()
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            active = await uow.essay_invites.count_active(essay.id, now)
            if active >= MAX_ACTIVE_INVITES:
                raise InviteLimitError(params={"limit": MAX_ACTIVE_INVITES})
            token = new_token()
            invite = EssayInvite(
                id=new_id(),
                essay_id=essay.id,
                student_id=essay.student_id,
                token_hash=token_hash(token),
                label=clean_label,
                audience=audience,
                can_comment=can_comment,
                expires_at=now + ttl,
                created_at=now,
            )
            stored = await uow.essay_invites.add(invite)
            await uow.commit()
        return CreatedInvite(stored, token)

    async def invites(self, ctx: AdmissionContext, essay_id: UUID) -> list[EssayInvite]:
        """List the links of my essay, revoked and expired ones included."""
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            return await uow.essay_invites.list_for_essay(essay.id)

    async def revoke(
        self, ctx: AdmissionContext, essay_id: UUID, invite_id: UUID
    ) -> None:
        """Switch a link off; its comments stay."""
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            invite = await uow.essay_invites.get(invite_id)
            if invite is None or invite.essay_id != essay.id:
                raise AdmissionNotFoundError()
            await uow.essay_invites.revoke(invite.id, self._clock.now())
            await uow.commit()

    async def feedback(
        self, ctx: AdmissionContext, essay_id: UUID
    ) -> list[FeedbackView]:
        """Every comment on my essay, placed in the current text."""
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            labels = {
                i.id: i.label for i in await uow.essay_invites.list_for_essay(essay.id)
            }
            items = await uow.essay_feedback.list_for_essay(essay.id)
        return [
            _view(f, essay.body, labels.get(f.invite_id) if f.invite_id else None)
            for f in items
        ]

    async def add_note(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        draft: CommentDraft,
        parent_id: UUID | None = None,
    ) -> FeedbackView:
        """Add my own note, or a reply to a comment with `parent_id`."""
        body = _body(draft)
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            if parent_id is not None:
                await self._feedback_of(uow, essay, parent_id)
            quote, anchor = _placed(essay.body, draft)
            item = Feedback(
                id=new_id(),
                essay_id=essay.id,
                student_id=essay.student_id,
                invite_id=None,
                parent_id=parent_id,
                quote=quote,
                anchor_start=anchor.start,
                anchor_end=anchor.end,
                body=body,
                author_name="",
                audience=None,
                created_at=self._clock.now(),
            )
            await uow.essay_feedback.add(item)
            await uow.commit()
        return _view(item, essay.body)

    @staticmethod
    async def _feedback_of(
        uow: AdmissionUnitOfWork, essay: Essay, feedback_id: UUID
    ) -> Feedback:
        item = await uow.essay_feedback.get(feedback_id)
        if item is None or item.essay_id != essay.id:
            raise AdmissionNotFoundError()
        return item

    async def set_resolved(
        self,
        ctx: AdmissionContext,
        essay_id: UUID,
        feedback_id: UUID,
        resolved: bool,
    ) -> FeedbackView:
        """Resolve a comment, or open it again."""
        at: datetime | None = self._clock.now() if resolved else None
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            item = await self._feedback_of(uow, essay, feedback_id)
            await uow.essay_feedback.set_resolved(item.id, at)
            await uow.commit()
        return _view(replace(item, resolved_at=at), essay.body)

    async def delete_feedback(
        self, ctx: AdmissionContext, essay_id: UUID, feedback_id: UUID
    ) -> None:
        """Delete a comment and its replies."""
        async with self._uow() as uow:
            essay = await self._own(uow, ctx, essay_id)
            item = await self._feedback_of(uow, essay, feedback_id)
            await uow.essay_feedback.delete(item.id)
            await uow.commit()

    async def _guest(
        self, uow: AdmissionUnitOfWork, token: str
    ) -> tuple[EssayInvite, Essay]:
        """Return the live link and its essay; every failure is the same 404."""
        invite = await uow.essay_invites.by_token_hash(token_hash(token))
        now = self._clock.now()
        if invite is None or not invite.is_active(now):
            raise InviteNotFoundError()
        essay = await uow.essays.get(invite.essay_id)
        if essay is None:
            raise InviteNotFoundError()
        return invite, essay

    async def open(self, token: str, ip: str | None) -> GuestView:
        """Open a link as a guest: the essay and the comments left through it."""
        await self._rl.hit(
            f"admission:invite_open:{_ip_bucket(ip)}",
            limit=OPENS_PER_HOUR,
            window_seconds=HOUR,
        )
        async with self._uow() as uow:
            invite, essay = await self._guest(uow, token)
            now = self._clock.now()
            await uow.essay_invites.touch(invite.id, now)
            items = await uow.essay_feedback.list_for_invite(invite.id)
            await uow.commit()
        views = [_view(f, essay.body) for f in items]
        return GuestView(essay, invite.opened(now), views)

    async def comment(
        self, token: str, author_name: str, draft: CommentDraft
    ) -> FeedbackView:
        """Leave a comment through a link that allows comments."""
        async with self._uow() as uow:
            invite, essay = await self._guest(uow, token)
            if not invite.can_comment:
                raise AdmissionForbiddenError(params={"permission": "comment"})
            author = check_text("author_name", author_name, AUTHOR_MAX)
            if author is None:
                raise ValidationFailedError(params={"field": "author_name"})
            body = _body(draft)
            quote, anchor = _placed(essay.body, draft)
            await self._rl.hit(
                f"admission:invite_comment:{invite.id}",
                limit=COMMENTS_PER_HOUR,
                window_seconds=HOUR,
            )
            item = Feedback(
                id=new_id(),
                essay_id=essay.id,
                student_id=essay.student_id,
                invite_id=invite.id,
                parent_id=None,
                quote=quote,
                anchor_start=anchor.start,
                anchor_end=anchor.end,
                body=body,
                author_name=author,
                audience=invite.audience,
                created_at=self._clock.now(),
            )
            await uow.essay_feedback.add(item)
            await uow.commit()
        return _view(item, essay.body)
