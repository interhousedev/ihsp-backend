"""In-memory ObjectStorage: same behaviour as S3Storage for what the module uses."""

import base64
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote

from app.modules.files.ports.storage import ObjectInfo, PresignedUpload


@dataclass(slots=True)
class StoredObject:
    """One object: bytes, content type and the checksum a PUT was signed with."""

    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class PutSignature:
    """What a presigned PUT binds (the browser must send exactly this)."""

    key: str
    content_type: str
    content_length: int
    sha256_b64: str


class InMemoryStorage:
    """Dict-backed storage; ``upload`` plays the browser that uses a presigned PUT."""

    def __init__(self) -> None:
        """Start empty."""
        self.objects: dict[str, StoredObject] = {}
        self.signatures: dict[str, PutSignature] = {}
        self.delete_batches: list[list[str]] = []
        self.get_urls: list[tuple[str, str, bool]] = []

    async def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        content_length: int,
        sha256_b64: str,
        expires: int = 300,
    ) -> PresignedUpload:
        """Remember what the URL binds and return a fake URL."""
        url = f"memory://bucket/{quote(key)}?expires={expires}"
        self.signatures[url] = PutSignature(
            key, content_type, content_length, sha256_b64
        )
        return PresignedUpload(
            url=url,
            headers={"Content-Type": content_type, "x-amz-checksum-sha256": sha256_b64},
        )

    def upload(self, upload: PresignedUpload, data: bytes) -> None:
        """Do what the browser does; refuse what the real server refuses."""
        signature = self.signatures[upload.url]
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        if len(data) != signature.content_length:
            raise ValueError("SignatureDoesNotMatch: Content-Length")
        if upload.headers.get("Content-Type") != signature.content_type:
            raise ValueError("SignatureDoesNotMatch: Content-Type")
        if digest != signature.sha256_b64:
            raise ValueError("BadDigest")
        self.objects[signature.key] = StoredObject(data, signature.content_type)

    def force_object(self, key: str, data: bytes, content_type: str = "x/y") -> None:
        """Put bytes under a key without any check (a client that cheated)."""
        self.objects[key] = StoredObject(data, content_type)

    async def presign_get(
        self,
        key: str,
        *,
        filename: str,
        inline: bool,
        content_type: str,
        expires: int = 60,
    ) -> str:
        """Return a fake URL and remember how it was requested."""
        self.get_urls.append((key, filename, inline))
        kind = "inline" if inline else "attachment"
        return f"memory://bucket/{quote(key)}?{kind}&expires={expires}"

    async def head(self, key: str) -> ObjectInfo | None:
        """Return size and SHA-256 of the object, or None."""
        obj = self.objects.get(key)
        if obj is None:
            return None
        digest = base64.b64encode(hashlib.sha256(obj.data).digest()).decode()
        return ObjectInfo(len(obj.data), digest, obj.content_type)

    async def read_range(self, key: str, start: int, end: int) -> bytes:
        """Return bytes start..end inclusive."""
        return self.objects[key].data[start : end + 1]

    async def get(self, key: str) -> bytes:
        """Return the whole object."""
        return self.objects[key].data

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write an object."""
        self.objects[key] = StoredObject(data, content_type)

    async def delete_many(self, keys: Sequence[str]) -> None:
        """Delete objects; missing keys are fine."""
        batch = list(dict.fromkeys(keys))
        self.delete_batches.append(batch)
        for key in batch:
            self.objects.pop(key, None)
