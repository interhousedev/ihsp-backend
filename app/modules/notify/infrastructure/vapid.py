"""VAPID key pairs for Web Push (generation and checks, no network)."""

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class VapidKeys:
    """A key pair in the form browsers and settings use (base64url, no padding)."""

    public_key: str  # uncompressed P-256 point, the `applicationServerKey`
    private_key: str  # the 32-byte scalar


def generate_vapid_keys() -> VapidKeys:
    """Make a new P-256 key pair."""
    vapid = Vapid02()
    vapid.generate_keys()
    scalar = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    return VapidKeys(public_key=public_key_of(vapid), private_key=_b64url(scalar))


def public_key_of(vapid: Vapid02) -> str:
    """The base64url public key of a loaded VAPID key."""
    point = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(point)


def load_private_key(private_key: str) -> Vapid02:
    """Load a base64url private key (raw scalar or DER)."""
    loaded: Vapid02 = Vapid02.from_string(private_key)
    return loaded
