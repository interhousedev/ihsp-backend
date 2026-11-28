"""Whose photo a student may see: active accounts that did not opt out."""

from dataclasses import replace

from app.shared.contracts.identity import UserStatus, peer_photo_ids
from app.shared.ids import new_id
from tests.academic.marks.fakes.identity import make_user
from tests.identity.support import make_user as make_account


def test_opted_out_and_inactive_users_are_dropped_except_the_viewer() -> None:
    """The viewer always sees their own photo; peers who opted out do not show."""
    me, peer, hidden, blocked = (new_id() for _ in range(4))
    users = {
        me: replace(make_user(me), hide_photo_from_public=True),
        peer: make_user(peer),
        hidden: replace(make_user(hidden), hide_photo_from_public=True),
        blocked: make_user(blocked, status=UserStatus.BLOCKED),
    }

    assert set(peer_photo_ids(me, users)) == {me, peer}
    assert set(peer_photo_ids(peer, users)) == {peer}


def test_user_ref_carries_the_photo_opt_out() -> None:
    """The batch user read already knows the opt-out, so no per-user lookup."""
    hidden = make_account(preferences={"hide_photo_from_public": True})
    assert hidden.to_ref().hide_photo_from_public is True
    assert make_account().to_ref().hide_photo_from_public is False
