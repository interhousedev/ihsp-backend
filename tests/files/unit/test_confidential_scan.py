"""Confidential files and scan status: the generic API refuses them."""

from uuid import uuid4

from app.modules.files.domain.errors import (
    ConfidentialFileError,
    FileQuarantinedError,
)
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PDF_TYPE, make_pdf, upload_ready

import pytest


async def _confidential(fakes: FilesFakes) -> object:
    return await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.SYSTEM,
        purpose=FilePurpose.LINK,
        name="passport.pdf",
        data=make_pdf("secret"),
        confidential=True,
    )


async def test_generic_api_refuses_confidential(fakes: FilesFakes) -> None:
    """download_url and read_bytes refuse; the signed route works, max 5 minutes."""
    ref = await _confidential(fakes)
    api = fakes.services.public
    assert ref.confidential  # type: ignore[attr-defined]
    with pytest.raises(ConfidentialFileError):
        await api.download_url(ref.id)  # type: ignore[attr-defined]
    with pytest.raises(ConfidentialFileError):
        await api.read_bytes(ref.id)  # type: ignore[attr-defined]
    signed = await api.issue_signed_download(  # type: ignore[attr-defined]
        ref.id, ttl_seconds=99999
    )
    assert signed.url


@pytest.mark.parametrize("status", ["pending", "infected", "failed"])
async def test_blocked_scans_are_not_downloadable(
    fakes: FilesFakes, student: Actor, status: str
) -> None:
    """Pending, infected and failed files are never served."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )
    api = fakes.services.public
    await api.set_scan_status(file_id, status)
    with pytest.raises(FileQuarantinedError):
        await api.download_url(file_id)
    with pytest.raises(FileQuarantinedError):
        await api.read_bytes(file_id)


@pytest.mark.parametrize("status", ["unscanned", "clean"])
async def test_unscanned_and_clean_are_downloadable(
    fakes: FilesFakes, student: Actor, status: str
) -> None:
    """Only the blocked states refuse."""
    file_id = await upload_ready(
        fakes, student, name="a.pdf", data=make_pdf("x"), content_type=PDF_TYPE
    )
    api = fakes.services.public
    await api.set_scan_status(file_id, status)
    assert await api.download_url(file_id)
