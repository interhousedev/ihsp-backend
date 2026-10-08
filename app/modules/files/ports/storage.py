"""Object storage port (S3-compatible)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """A presigned PUT: the URL and the headers the browser must send."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "PUT"


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """What HEAD tells about a stored object."""

    size: int
    checksum_sha256: str | None
    content_type: str | None


class ObjectStorage(Protocol):
    """Bytes of files; the backend never streams uploads through itself."""

    async def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        content_length: int,
        sha256_b64: str,
        expires: int = 300,
    ) -> PresignedUpload:
        """Return a PUT URL bound to the size, type and SHA-256."""
        ...

    async def presign_get(
        self,
        key: str,
        *,
        filename: str,
        inline: bool,
        content_type: str,
        expires: int = 60,
    ) -> str:
        """Return a GET URL that sets Content-Disposition and Content-Type."""
        ...

    async def head(self, key: str) -> ObjectInfo | None:
        """Return the object's size and checksum, or None when it is missing."""
        ...

    async def read_range(self, key: str, start: int, end: int) -> bytes:
        """Return bytes ``start..end`` (inclusive) of the object."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the whole object."""
        ...

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write an object."""
        ...

    async def delete_many(self, keys: Sequence[str]) -> None:
        """Delete objects (missing keys are fine), 1000 per request."""
        ...
