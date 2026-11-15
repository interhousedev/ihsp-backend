"""Use cases of the privacy module on fakes."""

import io
import zipfile

from app.modules.privacy.domain.errors import (
    ErasureNotPendingError,
    ErasureRequestNotFoundError,
    ExportNotFoundError,
    ExportRateLimitedError,
)
from app.modules.privacy.domain.models import ErasureStatus, ExportStatus
from app.modules.privacy.ports.gateways import OwnedFile
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.privacy.conftest import PrivacyHarness

import pytest


async def test_export_is_rate_limited_built_and_downloaded_by_its_owner(
    privacy: PrivacyHarness, kicker: FakeTaskKicker, clock: FixedClock
) -> None:
    """One export per day; the ZIP holds rows and files; only the owner downloads."""
    s, uid = privacy.services, privacy.user_id
    privacy.files.files[uid] = [OwnedFile("k/1", "a b.txt", 3)]
    privacy.storage.force_object("k/1", b"abc")
    job = await s.request_export.execute(uid)
    assert kicker.calls == [("privacy.build_export", {"export_id": str(job.id)})]
    with pytest.raises(ExportRateLimitedError):
        await s.request_export.execute(uid)

    assert await s.build_export.execute(job.id) is True
    assert await s.build_export.execute(job.id) is False
    [stored] = privacy.store.exports
    assert stored.status is ExportStatus.READY
    assert stored.storage_key is not None
    names = zipfile.ZipFile(
        io.BytesIO(privacy.storage.objects[stored.storage_key].data)
    ).namelist()
    assert names == ["data/id.sessions.json", "files/0000-a_b.txt"]
    assert privacy.accounts.notices[0][1] == "privacy-mail-export-ready"

    assert (await s.download_export.execute(uid, job.id)).startswith("memory://")
    other = privacy.admin.user_id
    with pytest.raises(ExportNotFoundError):
        await s.download_export.execute(other, job.id)

    clock.advance(hours=24 * 8)
    with pytest.raises(ExportNotFoundError):
        await s.download_export.execute(uid, job.id)
    assert await s.cleanup_exports.execute() == 1
    assert privacy.store.exports[0].storage_key is None


async def test_failed_build_marks_the_export_failed(privacy: PrivacyHarness) -> None:
    """A source error ends in FAILED, and the user may ask again."""
    privacy.source.fail = True
    job = await privacy.services.request_export.execute(privacy.user_id)
    assert await privacy.services.build_export.execute(job.id) is False
    assert privacy.store.exports[0].status is ExportStatus.FAILED
    await privacy.services.request_export.execute(privacy.user_id)


async def test_erasure_lifecycle(privacy: PrivacyHarness) -> None:
    """Request is idempotent; approve, decide twice, erase, complete."""
    s, uid, admin = privacy.services, privacy.user_id, privacy.admin.user_id
    t1 = await s.erasure.request(uid, ip=None, user_agent=None)
    t2 = await s.erasure.request(uid, ip=None, user_agent=None)
    assert t1 == t2 and t1.status == "pending_review"

    request = await s.approve_erasure.execute(t1.request_id, admin_id=admin, ip=None)
    assert request.status is ErasureStatus.APPROVED and request.closes_on
    assert privacy.accounts.started == [(uid, admin)]
    with pytest.raises(ErasureNotPendingError):
        await s.approve_erasure.execute(t1.request_id, admin_id=admin, ip=None)
    with pytest.raises(ErasureNotPendingError):
        await s.cancel_erasure.execute(uid)

    assert await s.erase_owner.execute(uid) == 1
    assert privacy.store.requests[0].status is ErasureStatus.COMPLETED
    assert await s.get_my_erasure.execute(uid) is None


async def test_reject_cancel_and_restore(privacy: PrivacyHarness) -> None:
    """Reject mails the reason; cancel and restore close the open request."""
    s, uid, admin = privacy.services, privacy.user_id, privacy.admin.user_id
    t = await s.erasure.request(uid, ip=None, user_agent=None)
    await s.reject_erasure.execute(t.request_id, admin_id=admin, reason="no", ip=None)
    assert privacy.accounts.notices[-1][2] == {"reason": "no"}
    entries = await s.list_erasure_requests.execute(None, limit=10, offset=0)
    assert entries[0].account is not None

    with pytest.raises(ErasureRequestNotFoundError):
        await s.cancel_erasure.execute(uid)
    await s.erasure.request(uid, ip=None, user_agent=None)
    cancelled = await s.cancel_erasure.execute(uid)
    assert cancelled.status is ErasureStatus.CANCELLED

    await s.erasure.request(uid, ip=None, user_agent=None)
    await s.erasure.restored(uid)
    assert privacy.store.requests[-1].status is ErasureStatus.CANCELLED
