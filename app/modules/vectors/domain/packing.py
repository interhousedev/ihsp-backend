"""Compact text form of a vector for the Redis cache (half precision, base64)."""

import base64
import struct
from collections.abc import Sequence


def pack(values: Sequence[float]) -> str:
    """2 bytes per number, base64: a 1024-dimension vector is 2.7 KB of text."""
    return base64.b64encode(struct.pack(f"<{len(values)}e", *values)).decode("ascii")


def unpack(text: str) -> list[float]:
    """The numbers of `pack` (rounded to half precision)."""
    raw = base64.b64decode(text)
    return list(struct.unpack(f"<{len(raw) // 2}e", raw))
