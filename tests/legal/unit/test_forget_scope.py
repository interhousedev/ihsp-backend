"""Forgetting an app scope deletes that scope's acceptances and forces re-consent."""

from uuid import UUID

from app.modules.legal.domain.errors import LegalAcceptanceRequiredError
from app.shared.contracts.legal import LegalItem
from tests.legal.conftest import LegalHarness

import pytest

ADM = "admission"


async def _accept(legal: LegalHarness, uid: UUID, kind: str, scope: str) -> None:
    await legal.services.accept.execute(
        uid,
        [LegalItem(kind, 1, scope)],
        ip=None,
        user_agent=None,
        app=scope,
        roles=["student"],
        guardian_attested=True,
    )


async def test_forget_scope_requires_consent_again(legal: LegalHarness) -> None:
    """Admission acceptances go, the global ones and other users' stay."""
    await legal.publish("privacy")
    await legal.publish("admission_privacy", ADM)
    uid = legal.student.user_id
    other = legal.admin.user_id
    for who in (uid, other):
        await _accept(legal, who, "privacy", "global")
        await _accept(legal, who, "admission_privacy", ADM)
    await legal.services.require_consent.execute(uid, ADM)

    await legal.services.forget_scope.execute(uid, ADM)

    with pytest.raises(LegalAcceptanceRequiredError):
        await legal.services.require_consent.execute(uid, ADM)
    await legal.services.require_consent.execute(uid)
    await legal.services.require_consent.execute(other, ADM)
    kept = {(a.user_id, a.app_scope) for a in legal.store.acceptances}
    assert kept == {(uid, "global"), (other, "global"), (other, ADM)}
