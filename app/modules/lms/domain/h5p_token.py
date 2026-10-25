"""Signed path tokens of stored H5P packages.

The player loads scripts, styles and media by relative URL with plain browser
requests (no ``Authorization`` header), so the base URL itself carries the right
to read: ``<course>.<package>.<expires>.<signature>``.
"""

import base64
import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

H5P_TOKEN_SECONDS = 4 * 3600


@dataclass(frozen=True, slots=True)
class H5PTokenClaims:
    """What a valid token grants: one package of one course until ``expires``."""

    course_id: UUID
    package_id: UUID
    expires: int


def _signature(key: bytes, payload: str) -> str:
    digest = hmac.new(key, payload.encode(), hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign_token(key: bytes, course_id: UUID, package_id: UUID, expires: int) -> str:
    """Return the token of the package, valid until the unix time ``expires``."""
    payload = f"{course_id.hex}.{package_id.hex}.{expires}"
    return f"{payload}.{_signature(key, payload)}"


def verify_token(key: bytes, token: str, *, now: int) -> H5PTokenClaims | None:
    """Return the claims of a valid, unexpired token, else None."""
    parts = token.split(".")
    if len(parts) != 4:
        return None
    course, package, expires, signature = parts
    payload = f"{course}.{package}.{expires}"
    if not hmac.compare_digest(signature, _signature(key, payload)):
        return None
    try:
        claims = H5PTokenClaims(UUID(hex=course), UUID(hex=package), int(expires))
    except ValueError:
        return None
    return claims if claims.expires > now else None


def package_prefix(course_id: UUID, package_id: UUID) -> str:
    """Return the object key prefix of an unpacked package."""
    return f"lms/courses/{course_id}/h5p/{package_id}/"
