"""Telegram mini app initData verification, HMAC method (telegram.md 6.2)."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.shared.base_error import UnauthorizedError
from app.shared.clock import Clock

CLOCK_SKEW = timedelta(seconds=60)


def _bad(reason: str) -> UnauthorizedError:
    return UnauthorizedError(support_details=f"initData: {reason}")


def _parse(raw: str) -> dict[str, str]:
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise _bad("malformed") from exc
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise _bad("duplicate fields")
    return fields


def _check_hash(fields: dict[str, str], bot_token: str) -> None:
    received = fields.get("hash")
    if not received:
        raise _bad("hash missing")
    # `signature` stays in the data-check string; only `hash` is left out.
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise _bad("bad hash")


def _check_age(fields: dict[str, str], max_age: timedelta, now: datetime) -> None:
    try:
        auth_date = datetime.fromtimestamp(int(fields["auth_date"]), tz=now.tzinfo)
    except (KeyError, ValueError, OverflowError, OSError) as exc:
        raise _bad("auth_date invalid") from exc
    if auth_date > now + CLOCK_SKEW:
        raise _bad("auth_date in the future")
    if now - auth_date > max_age:
        raise _bad("expired")


def _user(fields: dict[str, str]) -> InitDataUser:
    try:
        data: dict[str, Any] = json.loads(fields["user"])
        return InitDataUser(
            id=int(data["id"]),
            first_name=str(data.get("first_name", "")),
            last_name=data.get("last_name"),
            username=data.get("username"),
            language_code=data.get("language_code"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise _bad("user missing") from exc


def verify_init_data(
    raw: str, *, bot_token: str, max_age: timedelta, now: datetime
) -> InitDataUser:
    """Return the Telegram user named by initData or raise UnauthorizedError."""
    fields = _parse(raw)
    _check_hash(fields, bot_token)
    _check_age(fields, max_age, now)
    return _user(fields)


class HmacInitDataVerifier:
    """InitDataVerifier that checks the bot-token HMAC against the injected clock."""

    def __init__(self, *, bot_token: str, clock: Clock) -> None:
        """Keep the bot token and the clock."""
        self._bot_token = bot_token
        self._clock = clock

    def verify(self, raw: str, *, max_age: timedelta) -> InitDataUser:
        """Verify one initData string."""
        return verify_init_data(
            raw, bot_token=self._bot_token, max_age=max_age, now=self._clock.now()
        )
