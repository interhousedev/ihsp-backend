"""Drafts, publication, pending and acceptance of legal documents."""

from app.modules.legal.domain.errors import (
    LegalIncompleteError,
    LegalInvalidError,
    LegalNoDraftError,
    LegalNotFoundError,
    LegalStaleVersionError,
)
from app.shared.contracts.legal import LegalItem
from tests.legal.conftest import FULL, LegalHarness

import pytest


async def test_publish_needs_every_locale(legal: LegalHarness) -> None:
    """A draft with a missing translation cannot be published."""
    await legal.services.save_draft.execute(
        "terms",
        title={"uz": "A", "ru": "B"},
        body_markdown=FULL,
        announcement=None,
    )
    with pytest.raises(LegalIncompleteError) as info:
        await legal.services.publish.execute("terms", actor_id=legal.admin.user_id)
    assert info.value.params == {"fields": "title.en"}
    assert await legal.services.list_current.execute() == []


async def test_publish_without_draft_fails(legal: LegalHarness) -> None:
    """Nothing to publish."""
    with pytest.raises(LegalNoDraftError):
        await legal.services.publish.execute("ai", actor_id=legal.admin.user_id)


async def test_unknown_locale_is_invalid(legal: LegalHarness) -> None:
    """Only uz, ru and en are accepted as text keys."""
    with pytest.raises(LegalInvalidError):
        await legal.services.save_draft.execute(
            "ai", title={"de": "x"}, body_markdown={}, announcement=None
        )


async def test_one_draft_per_kind_and_versions_increase(legal: LegalHarness) -> None:
    """Saving twice edits the same draft; republishing makes version 2."""
    first = await legal.services.save_draft.execute(
        "privacy", title={"en": "a"}, body_markdown={}, announcement=None
    )
    second = await legal.services.save_draft.execute(
        "privacy", title=FULL, body_markdown=FULL, announcement=None
    )
    assert first.id == second.id
    assert len(legal.store.documents) == 1
    assert await legal.publish("privacy") == 1
    assert await legal.publish("privacy") == 2
    current = await legal.services.get_current.execute("privacy")
    assert current.version == 2
    assert [a.type for a in legal.store.audits] == ["legal.published"] * 2


async def test_get_current_of_unpublished_kind_is_not_found(
    legal: LegalHarness,
) -> None:
    """A draft is not public."""
    await legal.services.save_draft.execute(
        "terms", title=FULL, body_markdown=FULL, announcement=None
    )
    with pytest.raises(LegalNotFoundError):
        await legal.services.get_current.execute("terms")


async def test_pending_lists_unaccepted_current_versions(legal: LegalHarness) -> None:
    """Nothing pending before publication; new versions show the old accepted one."""
    uid = legal.student.user_id
    assert await legal.services.pending.execute(uid) == []
    await legal.publish("privacy")
    await legal.publish("terms")
    pending = await legal.services.pending.execute(uid)
    assert {(p.document.kind, p.document.version) for p in pending} == {
        ("privacy", 1),
        ("terms", 1),
    }
    left = await legal.services.accept.execute(
        uid,
        [LegalItem("privacy", 1), LegalItem("terms", 1)],
        ip="1.1.1.1",
        user_agent="t",
    )
    assert left == []
    assert len(legal.store.acceptances) == 2
    await legal.publish("privacy")
    pending = await legal.services.pending.execute(uid)
    assert [(p.document.kind, p.document.version) for p in pending] == [("privacy", 2)]
    assert pending[0].previously_accepted_version == 1


async def test_accepting_a_stale_version_records_nothing(legal: LegalHarness) -> None:
    """Only the current version can be accepted."""
    await legal.publish("privacy")
    await legal.publish("privacy")
    with pytest.raises(LegalStaleVersionError) as info:
        await legal.services.accept.execute(
            legal.student.user_id,
            [LegalItem("privacy", 2), LegalItem("privacy", 1)],
            ip=None,
            user_agent=None,
        )
    assert info.value.params == {"kind": "privacy", "current": 2}
    assert legal.store.acceptances == []


async def test_acceptance_counts_follow_current_versions(legal: LegalHarness) -> None:
    """Counted per current version, distinct users."""
    await legal.publish("privacy")
    await legal.services.accept.execute(
        legal.student.user_id, [LegalItem("privacy", 1)], ip=None, user_agent=None
    )
    await legal.services.accept.execute(
        legal.student.user_id, [LegalItem("privacy", 1)], ip=None, user_agent=None
    )
    counts = await legal.services.count_acceptances.execute()
    assert [(c.kind, c.version, c.accepted_count) for c in counts] == [
        ("privacy", 1, 1)
    ]
