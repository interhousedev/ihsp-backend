"""ID-19, ID-20, UF-BOT-01: Telegram initData verification (HMAC method)."""

from datetime import UTC, datetime, timedelta

from app.modules.identity.infrastructure.telegram.init_data import verify_init_data
from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.shared.base_error import UnauthorizedError
from tests.identity.support import BOT_TOKEN, sign_init_data

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
NO_DELTA = timedelta(0)


def verify(
    raw: str, *, max_age: timedelta = HOUR, token: str = BOT_TOKEN
) -> InitDataUser:
    """Verify against the fixed clock."""
    return verify_init_data(raw, bot_token=token, max_age=max_age, now=NOW)


def stamp(delta: timedelta = NO_DELTA) -> int:
    """auth_date relative to NOW."""
    return int((NOW + delta).timestamp())


def test_valid_init_data_names_the_telegram_user() -> None:
    """ID-19: the user id comes only from signed data."""
    user = verify(
        sign_init_data(telegram_id=99, auth_date=stamp(-timedelta(minutes=5)))
    )

    assert (user.id, user.username, user.first_name, user.language_code) == (
        99,
        "aleksey",
        "Aleksey",
        "ru",
    )


def test_user_without_a_username_is_fine() -> None:
    """Telegram accounts may have no @username."""
    user = verify(sign_init_data(username=None, auth_date=stamp()))

    assert user.username is None


def test_tampered_field_fails() -> None:
    """ID-20: changing the user breaks the hash."""
    raw = sign_init_data(auth_date=stamp())

    with pytest.raises(UnauthorizedError):
        verify(raw.replace("aleksey", "mallory"))


def test_wrong_bot_token_fails() -> None:
    """Data signed for another bot is refused."""
    raw = sign_init_data(auth_date=stamp(), bot_token="111:other")

    with pytest.raises(UnauthorizedError):
        verify(raw)


def test_data_older_than_the_limit_fails() -> None:
    """UF-BOT-01 3b: expired initData."""
    raw = sign_init_data(auth_date=stamp(-timedelta(hours=25)))

    with pytest.raises(UnauthorizedError):
        verify(raw, max_age=timedelta(hours=24))


def test_data_within_the_limit_passes() -> None:
    """The limit is inclusive of recent data."""
    raw = sign_init_data(auth_date=stamp(-timedelta(hours=23)))

    assert verify(raw, max_age=timedelta(hours=24)).id == 555


def test_auth_date_far_in_the_future_fails() -> None:
    """A clock far ahead of ours is suspicious."""
    raw = sign_init_data(auth_date=stamp(timedelta(minutes=5)))

    with pytest.raises(UnauthorizedError):
        verify(raw)


def test_missing_hash_or_garbage_fails() -> None:
    """Malformed input never reaches the user lookup."""
    for raw in ("", "auth_date=1", "not a query string"):
        with pytest.raises(UnauthorizedError):
            verify(raw)
