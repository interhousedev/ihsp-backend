"""A student whose essay key is gone fails closed with a 503 domain error."""

from uuid import UUID

from app.modules.admission.domain.errors import EssayKeyUnavailableError
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)

OWNER = UUID("00000000-0000-0000-0000-0000000000e1")
RECORD = UUID("00000000-0000-0000-0000-0000000000e2")


async def test_missing_key_answers_503_not_a_bare_value_error() -> None:
    """ADM-CRYPT-KEY-1: a blob whose key is no longer in the store raises 503."""
    blob = await AesGcmEssayCipher(MemoryEssayKeyStore()).seal(
        OWNER, RECORD, "body", "draft"
    )
    other_process = AesGcmEssayCipher(MemoryEssayKeyStore())
    try:
        await other_process.open(OWNER, RECORD, "body", blob)
    except EssayKeyUnavailableError as exc:
        assert exc.status == 503
        assert exc.code == "admission/essay_key_unavailable"
    else:
        raise AssertionError("open must fail without the key")


async def test_new_essay_after_key_loss_gets_a_key() -> None:
    """ADM-CRYPT-KEY-2: sealing for an owner without a key creates one and opens."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    blob = await cipher.seal(OWNER, RECORD, "body", "fresh")
    assert await cipher.open(OWNER, RECORD, "body", blob) == "fresh"
