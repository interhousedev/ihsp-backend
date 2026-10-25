"""Validation of outbound recipients (MAIL-6)."""

from collections.abc import Sequence

from app.modules.mail.domain.errors import (
    InvalidRecipientError,
    NoRecipientsError,
    TooManyRecipientsError,
)

from email_validator import EmailNotValidError, validate_email


def validate_recipients(addresses: Sequence[str], limit: int) -> list[str]:
    """Return normalized unique addresses; at least one, at most ``limit``."""
    unique: dict[str, str] = {}
    for address in addresses:
        value = address.strip()
        if not value:
            continue
        try:
            normalized = validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise InvalidRecipientError(params={"address": value}) from exc
        unique.setdefault(normalized.lower(), normalized)
    if not unique:
        raise NoRecipientsError()
    if len(unique) > limit:
        raise TooManyRecipientsError(params={"limit": limit})
    return list(unique.values())
