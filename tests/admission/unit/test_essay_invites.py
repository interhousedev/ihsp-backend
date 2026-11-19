"""Essay review links: limits, ownership, guest access and anchoring."""

from uuid import UUID

from app.modules.admission.application.essay_invites import CommentDraft
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    InviteLimitError,
    InviteNotFoundError,
)
from app.modules.admission.domain.essay_invites import (
    BODY_MAX,
    check_ttl,
    reanchor,
    token_hash,
)
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes_invites import InviteDesk
from tests.admission.unit.test_items_service import OTHER

import pytest

TEXT = "I learned to listen. Then I learned to lead."


async def _essay(d: InviteDesk, body: str = TEXT) -> UUID:
    ctx = await d.w.ctx()
    e = await d.essay_svc.create(ctx, {"title": "Why me", "word_limit": 650})
    await d.essay_svc.save(ctx, e.id, 0, {"body": body})
    return e.id


async def _link(d: InviteDesk, essay_id: UUID, **kw: object) -> str:
    made = await d.svc.create(
        await d.w.ctx(), essay_id, audience="parent", **kw  # type: ignore[arg-type]
    )
    return made.token


async def test_twenty_active_links_then_limit() -> None:
    """ADM-INV-1: 20 active links are allowed, the 21st is refused."""
    d = InviteDesk()
    eid = await _essay(d)
    ctx = await d.w.ctx()
    for _ in range(20):
        await d.svc.create(ctx, eid, audience="classmate")
    with pytest.raises(InviteLimitError):
        await d.svc.create(ctx, eid, audience="classmate")


async def test_revoked_links_do_not_count() -> None:
    """ADM-INV-2: a revoked link frees a slot."""
    d = InviteDesk()
    eid = await _essay(d)
    ctx = await d.w.ctx()
    made = [await d.svc.create(ctx, eid, audience="parent") for _ in range(20)]
    await d.svc.revoke(ctx, eid, made[0].invite.id)
    await d.svc.create(ctx, eid, audience="parent")
    assert len(await d.svc.invites(ctx, eid)) == 21


@pytest.mark.parametrize("days", [0, 91])
def test_ttl_out_of_range(days: int) -> None:
    """ADM-INV-3: a lifetime outside 1..90 days is refused."""
    with pytest.raises(ValidationFailedError):
        check_ttl(days)


@pytest.mark.parametrize("days", [1, 90])
def test_ttl_bounds_accepted(days: int) -> None:
    """ADM-INV-4: 1 and 90 days are accepted."""
    assert check_ttl(days).days == days


async def test_token_is_stored_only_as_hash() -> None:
    """ADM-INV-5: the plain token is never stored."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid)
    (row,) = d.invites.rows.values()
    assert row.token_hash == token_hash(token) and row.token_hash != token


async def test_foreign_student_gets_not_found() -> None:
    """ADM-INV-6: another student's essay answers 404 everywhere."""
    d = InviteDesk()
    eid = await _essay(d)
    other = await d.w.ctx(OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.create(other, eid, audience="parent")
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.invites(other, eid)
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.feedback(other, eid)


async def test_guest_opens_without_identity() -> None:
    """ADM-INV-7: a valid link opens the essay and records the visit."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid)
    view = await d.svc.open(token, "203.0.113.5")
    assert view.essay.body == TEXT
    assert view.invite.last_opened_at == d.clock.now()


async def test_unknown_expired_revoked_and_deleted_look_the_same() -> None:
    """ADM-INV-8: every dead link answers the same not found."""
    d = InviteDesk()
    eid = await _essay(d)
    ctx = await d.w.ctx()
    with pytest.raises(InviteNotFoundError):
        await d.svc.open("no-such-token", None)
    revoked = await d.svc.create(ctx, eid, audience="parent")
    await d.svc.revoke(ctx, eid, revoked.invite.id)
    with pytest.raises(InviteNotFoundError):
        await d.svc.open(revoked.token, None)
    deleted = await _link(d, eid)
    expiring = await _link(d, eid, ttl_days=1)
    d.clock.advance(days=1)
    with pytest.raises(InviteNotFoundError):
        await d.svc.open(expiring, None)
    d.essays.rows.pop(eid)
    with pytest.raises(InviteNotFoundError):
        await d.svc.open(deleted, None)


async def test_read_only_link_cannot_comment() -> None:
    """ADM-INV-9: a read-only link refuses comments with 403."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid, can_comment=False)
    with pytest.raises(AdmissionForbiddenError):
        await d.svc.comment(token, "Mum", CommentDraft("Nice"))


async def test_comment_anchors_and_student_sees_label() -> None:
    """ADM-INV-10: a quoted comment is anchored and shown to the student."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid, label="Mum")
    start = TEXT.index("listen")
    draft = CommentDraft("Lovely", "listen", start, start + 6)
    out = await d.svc.comment(token, "Mum", draft)
    assert (out.anchor.start, out.anchor.detached) == (start, False)
    (view,) = await d.svc.feedback(await d.w.ctx(), eid)
    assert view.invite_label == "Mum" and view.item.author_name == "Mum"


async def test_quote_not_in_text_is_refused() -> None:
    """ADM-INV-11: a guest cannot quote text the essay does not contain."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid)
    with pytest.raises(ValidationFailedError):
        await d.svc.comment(token, "Mum", CommentDraft("Hm", "absent words", 0, 12))


def test_reanchor_exact_moved_and_deleted() -> None:
    """ADM-INV-12: quotes keep, follow or lose their place."""
    start = TEXT.index("lead")
    assert reanchor(TEXT, "lead", start, start + 4).start == start
    moved = "Intro. " + TEXT
    assert reanchor(moved, "lead", start, start + 4).start == start + 7
    gone = reanchor("A new essay.", "lead", start, start + 4)
    assert gone.detached and gone.start is None


async def test_comment_rate_limit_per_link() -> None:
    """ADM-INV-13: 20 comments an hour per link, then 429 until the hour passes."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid)
    for n in range(20):
        await d.svc.comment(token, "Mum", CommentDraft(f"note {n}"))
    with pytest.raises(RateLimitedError):
        await d.svc.comment(token, "Mum", CommentDraft("one more"))
    d.clock.advance(hours=1)
    await d.svc.comment(token, "Mum", CommentDraft("next hour"))


async def test_body_length_limit() -> None:
    """ADM-INV-14: 2000 characters are allowed, 2001 are refused."""
    d = InviteDesk()
    eid = await _essay(d)
    token = await _link(d, eid)
    await d.svc.comment(token, "Mum", CommentDraft("x" * BODY_MAX))
    with pytest.raises(CharLimitError):
        await d.svc.comment(token, "Mum", CommentDraft("x" * (BODY_MAX + 1)))


async def test_student_replies_resolves_and_deletes() -> None:
    """ADM-INV-15: the student replies, resolves, and deletes with replies."""
    d = InviteDesk()
    eid = await _essay(d)
    ctx = await d.w.ctx()
    token = await _link(d, eid)
    root = await d.svc.comment(token, "Mum", CommentDraft("Shorter?"))
    await d.svc.add_note(ctx, eid, CommentDraft("Done"), root.item.id)
    done = await d.svc.set_resolved(ctx, eid, root.item.id, True)
    assert done.item.resolved_at == d.clock.now()
    await d.svc.delete_feedback(ctx, eid, root.item.id)
    assert await d.svc.feedback(ctx, eid) == []
    with pytest.raises(AdmissionNotFoundError):
        await d.svc.delete_feedback(ctx, eid, new_id())
