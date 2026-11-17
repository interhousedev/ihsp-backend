"""Opportunity comment moderation states and organization validation."""

import dataclasses

from app.modules.admission.domain import opportunity_comments as oc
from app.modules.admission.domain.errors import InvalidTransitionError
from app.modules.admission.domain.opportunity_comments import (
    OppComment,
    OppCommentReport,
)
from app.modules.admission.domain.orgs import Organization
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW

import pytest

STAFF = new_id()
AUTHOR = new_id()


def _comment(**kw: object) -> OppComment:
    base = OppComment(
        id=new_id(),
        opportunity_id=new_id(),
        author_id=AUTHOR,
        body="Useful",
        created_at=NOW,
    )
    return dataclasses.replace(base, **kw)  # type: ignore[arg-type]


def _report() -> OppCommentReport:
    return OppCommentReport(
        id=new_id(),
        comment_id=new_id(),
        reporter_id=new_id(),
        reason="spam",
        created_at=NOW,
    )


def test_hide_then_unhide_round_trip() -> None:
    hidden = oc.hide(_comment(), STAFF, NOW)
    assert (hidden.status, hidden.hidden_by, hidden.hidden_at) == (
        "hidden",
        STAFF,
        NOW,
    )
    back = oc.unhide(hidden)
    assert (back.status, back.hidden_by, back.hidden_at) == ("published", None, None)


def test_hide_requires_published_and_unhide_requires_hidden() -> None:
    with pytest.raises(InvalidTransitionError):
        oc.unhide(_comment())
    with pytest.raises(InvalidTransitionError):
        oc.hide(_comment(status="hidden"), STAFF, NOW)
    with pytest.raises(InvalidTransitionError):
        oc.hide(_comment(status="deleted"), STAFF, NOW)


def test_delete_is_terminal() -> None:
    gone = oc.delete(_comment(status="hidden"), NOW)
    assert gone.status == "deleted" and gone.deleted_at == NOW
    with pytest.raises(InvalidTransitionError):
        oc.delete(gone, NOW)
    with pytest.raises(InvalidTransitionError):
        oc.unhide(gone)


def test_only_foreign_published_comments_are_reportable() -> None:
    other = new_id()
    assert oc.may_report(_comment(), other)
    assert not oc.may_report(_comment(), AUTHOR)
    assert not oc.may_report(_comment(status="hidden"), other)
    assert not oc.may_report(_comment(status="deleted"), other)


def test_report_closes_once() -> None:
    done = oc.close_report(_report(), "dismissed", STAFF, NOW)
    assert (done.status, done.resolved_by, done.resolved_at) == (
        "dismissed",
        STAFF,
        NOW,
    )
    with pytest.raises(InvalidTransitionError):
        oc.close_report(done, "resolved", STAFF, NOW)
    with pytest.raises(InvalidTransitionError):
        oc.close_report(_report(), "open", STAFF, NOW)


def test_body_limits() -> None:
    assert oc.body_problem("   ")
    assert oc.body_problem("x" * (oc.BODY_MAX + 1))
    assert not oc.body_problem("x" * oc.BODY_MAX)


def test_organization_requires_name() -> None:
    org = Organization(
        id=new_id(), name="Acme", kind="company", created_at=NOW, updated_at=NOW
    )
    assert not org.problems()
    assert dataclasses.replace(org, name=" ").problems()
