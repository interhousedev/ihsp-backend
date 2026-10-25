"""EMIS ID as a sign-in identifier: the format rule, masking and the lookup errors."""

import hashlib
import re

from app.shared.base_error import BaseError

EMIS_ID_PATTERN = re.compile(r"^\d{5,12}$")
MASK_KEEP = 2
EMIS_LOGIN_LOOKUP = "login.emis_lookup"


class EmisLoginInvalidError(BaseError):
    """The entered EMIS ID is not a number of 5 to 12 digits."""

    code = "identity/emis-login-invalid"
    status = 422
    message_key = "id-emis-login-invalid"


class EmisLoginNotFoundError(BaseError):
    """No active account is linked to the EMIS ID."""

    code = "identity/emis-login-not-found"
    status = 404
    message_key = "id-emis-login-not-found"


def validate_emis_id(raw: str) -> str:
    """Return the EMIS ID without surrounding spaces; reject anything but digits."""
    emis_id = raw.strip()
    if not EMIS_ID_PATTERN.fullmatch(emis_id):
        raise EmisLoginInvalidError()
    return emis_id


def mask_emis_id(emis_id: str) -> str:
    """Hide all but the last two digits, for logs and audit rows."""
    return "*" * max(len(emis_id) - MASK_KEEP, 0) + emis_id[-MASK_KEEP:]


def emis_id_fingerprint(emis_id: str) -> str:
    """A stable, non-reversible key for per-identifier counters."""
    return hashlib.sha256(emis_id.encode()).hexdigest()[:24]
