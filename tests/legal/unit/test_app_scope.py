"""App-scoped documents: pending per app, re-consent, guardian attestation."""

from app.modules.legal.domain.errors import (
    LegalAcceptanceRequiredError,
    LegalGuardianAttestationRequiredError,
    LegalInvalidError,
    LegalStaleVersionError,
)
from app.shared.contracts.legal import LegalItem, normalize_app
from tests.legal.conftest import FULL, LegalHarness

import pytest

ADM = "admission"
STUDENT_ROLES = ["student"]


def _item(kind: str = "admission_privacy", version: int = 1) -> LegalItem:
    return LegalItem(kind, version, ADM)


async def _accept_admission(
    legal: LegalHarness, *items: LegalItem, attested: bool = True
) -> None:
    await legal.services.accept.execute(
        legal.student.user_id,
        items,
        ip=None,
        user_agent=None,
        app=ADM,
        roles=STUDENT_ROLES,
        guardian_attested=attested,
    )


def test_unknown_app_header_is_global() -> None:
    """Only known app names scope the gate."""
    assert normalize_app("Admission") == ADM
    assert normalize_app("evil") == "global"
    assert normalize_app(None) == "global"


async def test_pending_is_global_plus_the_app(legal: LegalHarness) -> None:
    """Admission documents are pending in the admission app only."""
    uid = legal.student.user_id
    await legal.publish("privacy")
    await legal.publish("admission_privacy", ADM)
    in_global = await legal.services.pending.execute(uid)
    in_adm = await legal.services.pending.execute(uid, ADM)
    assert {(p.document.kind, p.document.app_scope) for p in in_global} == {
        ("privacy", "global")
    }
    assert {(p.document.kind, p.document.app_scope) for p in in_adm} == {
        ("privacy", "global"),
        ("admission_privacy", ADM),
    }


async def test_gate_blocks_only_the_app(legal: LegalHarness) -> None:
    """Global consent passes elsewhere; the admission gate asks for its own."""
    uid = legal.student.user_id
    await legal.publish("privacy")
    await legal.services.accept.execute(
        uid, [LegalItem("privacy", 1)], ip=None, user_agent=None
    )
    await legal.publish("admission_terms", ADM)
    await legal.services.require_consent.execute(uid)
    with pytest.raises(LegalAcceptanceRequiredError) as info:
        await legal.services.require_consent.execute(uid, ADM)
    assert info.value.params == {"kinds": "admission_terms"}


async def test_republishing_requires_consent_again(legal: LegalHarness) -> None:
    """Publishing a new version drops cached passes and blocks the app."""
    uid = legal.student.user_id
    await legal.publish("admission_privacy", ADM)
    await _accept_admission(legal, _item())
    await legal.services.require_consent.execute(uid, ADM)
    assert await legal.publish("admission_privacy", ADM) == 2
    with pytest.raises(LegalAcceptanceRequiredError):
        await legal.services.require_consent.execute(uid, ADM)
    pending = await legal.services.pending.execute(uid, ADM)
    assert pending[0].previously_accepted_version == 1
    await _accept_admission(legal, _item(version=2))
    await legal.services.require_consent.execute(uid, ADM)


async def test_guardian_attestation_is_required_for_students(
    legal: LegalHarness,
) -> None:
    """A student account cannot accept app documents without the attestation."""
    await legal.publish("admission_privacy", ADM)
    with pytest.raises(LegalGuardianAttestationRequiredError):
        await _accept_admission(legal, _item(), attested=False)
    assert legal.store.acceptances == []
    await _accept_admission(legal, _item(), attested=True)
    (row,) = legal.store.acceptances
    assert row.guardian_attested and row.app_scope == ADM


async def test_staff_and_global_documents_need_no_attestation(
    legal: LegalHarness,
) -> None:
    """Staff accept app documents alone; global documents never need it."""
    await legal.publish("privacy")
    await legal.publish("admission_privacy", ADM)
    uid = legal.student.user_id
    await legal.services.accept.execute(
        uid, [LegalItem("privacy", 1)], ip=None, user_agent=None, roles=STUDENT_ROLES
    )
    await legal.services.accept.execute(
        uid, [_item()], ip=None, user_agent=None, app=ADM, roles=["counselor"]
    )
    assert [a.guardian_attested for a in legal.store.acceptances] == [False, False]


async def test_stale_app_version_is_rejected(legal: LegalHarness) -> None:
    """The version must be the current one of the same scope."""
    await legal.publish("admission_privacy", ADM)
    await legal.publish("admission_privacy", ADM)
    with pytest.raises(LegalStaleVersionError) as info:
        await _accept_admission(legal, _item(version=1))
    assert info.value.params == {"kind": "admission_privacy", "current": 2}
    with pytest.raises(LegalStaleVersionError):
        await _accept_admission(legal, LegalItem("admission_privacy", 2, "global"))
    assert legal.store.acceptances == []


async def test_versions_count_per_scope_and_admission_kinds_stay_in_admission(
    legal: LegalHarness,
) -> None:
    """Scopes number versions separately; admission kinds are not global."""
    await legal.publish("terms")
    await legal.publish("terms", "lms")
    assert [d.version for d in await legal.services.list_all.execute()] == [1, 1]
    with pytest.raises(LegalInvalidError):
        await legal.services.save_draft.execute(
            "admission_terms",
            title=FULL,
            body_markdown=FULL,
            announcement=None,
            app_scope="global",
        )
    with pytest.raises(LegalInvalidError):
        await legal.services.save_draft.execute(
            "terms", title=FULL, body_markdown=FULL, announcement=None, app_scope="x"
        )


async def test_overview_groups_by_scope_with_counts(legal: LegalHarness) -> None:
    """Global first, then apps, each with versions, draft and acceptances."""
    await legal.publish("privacy")
    await legal.publish("admission_terms", ADM)
    await _accept_admission(legal, _item("admission_terms"))
    await legal.services.save_draft.execute(
        "admission_terms",
        title={"en": "n"},
        body_markdown={},
        announcement=None,
        app_scope=ADM,
    )
    groups = await legal.services.overview.execute()
    assert [g.app_scope for g in groups] == ["global", ADM]
    (kind,) = groups[1].kinds
    assert (kind.current_version, kind.accepted_count) == (1, 1)
    assert kind.draft is not None and kind.draft.version == 2
    assert [v.version for v in kind.versions] == [2, 1]
