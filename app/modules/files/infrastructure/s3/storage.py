"""S3-compatible object storage over aiobotocore (RustFS in dev, any S3 in prod).

Two clients are used on purpose. ``presign_client`` has the *public* endpoint:
a presigned URL is bound to the Host it was signed for, so URLs for browsers must
be signed with the host the browser will call. ``client`` has the internal
endpoint and does the real I/O (HEAD, GET, PUT, DELETE).
"""

import asyncio
import urllib.parse
from collections.abc import Sequence
from contextlib import AsyncExitStack
from typing import Any

from app.modules.files.domain.errors import StorageError
from app.modules.files.ports.storage import ObjectInfo, PresignedUpload

import structlog
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

log = structlog.get_logger(__name__)

DELETE_BATCH = 1000
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})

S3_CONFIG = AioConfig(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    # botocore >= 1.36 would add CRC32 to uploads of third-party S3 servers otherwise.
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
    connect_timeout=5,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
)


def content_disposition(name: str, *, inline: bool) -> str:
    """Build a Content-Disposition value with an ASCII fallback and RFC 5987 name."""
    fallback = name.encode("ascii", "replace").decode()
    fallback = "".join(
        "_" if ch in '?"\\' or ord(ch) < 32 or ord(ch) == 127 else ch for ch in fallback
    )
    kind = "inline" if inline else "attachment"
    quoted = urllib.parse.quote(name, safe="")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quoted}"


class S3Storage:
    """ObjectStorage implementation for one bucket."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        public_endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        """Remember connection settings; clients are created on first use."""
        self._endpoint_url = endpoint_url
        self._public_endpoint_url = public_endpoint_url
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()
        self._client: Any = None
        self._presign_client: Any = None

    async def _create(self, endpoint_url: str) -> Any:
        """Create one S3 client inside the exit stack."""
        return await self._stack.enter_async_context(
            get_session().create_client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=S3_CONFIG,
            )
        )

    async def _io(self) -> Any:
        """Return the internal-endpoint client."""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await self._create(self._endpoint_url)
        return self._client

    async def _signer(self) -> Any:
        """Return the public-endpoint client used only for presigning."""
        if self._presign_client is None:
            async with self._lock:
                if self._presign_client is None:
                    self._presign_client = await self._create(self._public_endpoint_url)
        return self._presign_client

    def _refused(self, exc: ClientError, op: str, key: str) -> StorageError:
        """Log a refused request (bucket, key, S3 code) and return the domain error."""
        error = exc.response.get("Error", {})
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        log.error(
            "s3_request_refused",
            op=op,
            bucket=self._bucket,
            key=key,
            code=error.get("Code"),
            http_status=status,
        )
        return StorageError(support_details=f"s3 {op} refused: {error.get('Code')}")

    async def close(self) -> None:
        """Close both clients."""
        await self._stack.aclose()
        self._client = None
        self._presign_client = None

    async def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        content_length: int,
        sha256_b64: str,
        expires: int = 300,
    ) -> PresignedUpload:
        """Return a PUT URL that enforces size, type and SHA-256 on the server."""
        signer = await self._signer()
        url: str = await signer.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
                "ChecksumSHA256": sha256_b64,
            },
            ExpiresIn=expires,
        )
        headers = {"Content-Type": content_type, "x-amz-checksum-sha256": sha256_b64}
        return PresignedUpload(url=url, headers=headers)

    async def presign_get(
        self,
        key: str,
        *,
        filename: str,
        inline: bool,
        content_type: str,
        expires: int = 60,
    ) -> str:
        """Return a GET URL with Content-Disposition and Content-Type overrides."""
        signer = await self._signer()
        url: str = await signer.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": content_disposition(
                    filename, inline=inline
                ),
                "ResponseContentType": content_type,
            },
            ExpiresIn=expires,
        )
        return url

    async def head(self, key: str) -> ObjectInfo | None:
        """Return size, checksum and type of an object, or None when missing."""
        client = await self._io()
        try:
            head = await client.head_object(
                Bucket=self._bucket, Key=key, ChecksumMode="ENABLED"
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in _MISSING_CODES:
                return None
            raise self._refused(exc, "head", key) from exc
        return ObjectInfo(
            size=int(head["ContentLength"]),
            checksum_sha256=head.get("ChecksumSHA256"),
            content_type=head.get("ContentType"),
        )

    async def read_range(self, key: str, start: int, end: int) -> bytes:
        """Return bytes ``start..end`` (inclusive)."""
        client = await self._io()
        try:
            response = await client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}"
            )
        except ClientError as exc:
            raise self._refused(exc, "get", key) from exc
        async with response["Body"] as stream:
            data: bytes = await stream.read()
        return data

    async def get(self, key: str) -> bytes:
        """Return the whole object."""
        client = await self._io()
        try:
            response = await client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise self._refused(exc, "get", key) from exc
        async with response["Body"] as stream:
            data: bytes = await stream.read()
        return data

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write an object."""
        client = await self._io()
        try:
            await client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except ClientError as exc:
            raise self._refused(exc, "put", key) from exc

    async def delete_many(self, keys: Sequence[str]) -> None:
        """Delete objects in batches of 1000; keys that do not exist are fine."""
        unique = list(dict.fromkeys(keys))
        client = await self._io()
        for start in range(0, len(unique), DELETE_BATCH):
            batch = unique[start : start + DELETE_BATCH]
            try:
                response = await client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
            except ClientError as exc:
                raise self._refused(exc, "delete", batch[0]) from exc
            errors = response.get("Errors")
            if errors:
                log.error("s3_delete_failed", errors=errors[:5], count=len(errors))
                raise StorageError(
                    support_details=f"{len(errors)} objects were not deleted"
                )
