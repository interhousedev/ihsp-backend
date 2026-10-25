"""ID-4: Argon2id hashing used by registration, reclaim and deletion."""

from app.modules.identity.infrastructure.emis.password_hasher import (
    Argon2PasswordHasher,
)


async def test_a_hash_is_argon2id_and_verifies_only_the_right_password() -> None:
    """ID-4: Argon2id, salted."""
    hasher = Argon2PasswordHasher()

    first = await hasher.hash("Secret123")
    second = await hasher.hash("Secret123")

    assert first.startswith("$argon2id$")
    assert first != second
    assert await hasher.verify(first, "Secret123")
    assert not await hasher.verify(first, "Secret124")


async def test_a_malformed_hash_never_matches() -> None:
    """ID-4: garbage in the database is a failed login, not a crash."""
    assert not await Argon2PasswordHasher().verify("not-a-hash", "Secret123")
