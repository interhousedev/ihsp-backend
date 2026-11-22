"""Mirror external images into S3 under `admission/org-media/<sha256>.<ext>`."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.modules.admission.domain.errors import MediaUnreachableError

import httpx
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session

USER_AGENT = "IHT-Admission-MediaMirror/1.0"
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
PREFIX = "admission/org-media/"
EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
"""SVG is rejected on purpose: it can carry scripts."""

Put = Callable[[str, bytes, str], Awaitable[None]]
Resolve = Callable[[str], Awaitable[list[str]]]


def sniff_type(data: bytes) -> str | None:
    """Return the image type of the leading bytes, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


async def resolve_host(host: str) -> list[str]:
    """Return the addresses of a host."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return list({str(i[4][0]) for i in infos})


def _public(addresses: list[str]) -> bool:
    return bool(addresses) and all(
        ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses
    )


class S3Put:
    """Writes objects with the internal S3 endpoint."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        acl: str = "",
    ) -> None:
        """Keep the connection settings; a client is opened per write."""
        self._acl = acl
        self._args: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "region_name": region,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "config": AioConfig(
                signature_version="s3v4", s3={"addressing_style": "path"}
            ),
        }
        self._bucket = bucket

    async def __call__(self, key: str, data: bytes, content_type: str) -> None:
        """Write one object."""
        async with get_session().create_client("s3", **self._args) as client:
            extra = {"ACL": self._acl} if self._acl else {}
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                **extra,
            )


class HttpS3MediaMirror:
    """Downloads an image over https and stores it content-addressed."""

    def __init__(
        self,
        put: Put,
        public_base: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolve: Resolve = resolve_host,
    ) -> None:
        """`public_base` is `<public endpoint>/<bucket>`, without a trailing slash."""
        self._put = put
        self._base = public_base.rstrip("/")
        self.own_prefix = f"{self._base}/{PREFIX}"
        self._transport = transport
        self._resolve = resolve

    async def mirror(self, url: str) -> str:
        """Return the storage URL for `url`; own URLs are kept."""
        if url.startswith(self.own_prefix):
            return url
        data = await self._download(url)
        content_type = sniff_type(data)
        if content_type is None:
            raise MediaUnreachableError(params={"url": url})
        key = f"{PREFIX}{hashlib.sha256(data).hexdigest()}.{EXTENSIONS[content_type]}"
        try:
            await self._put(key, data, content_type)
        except Exception as exc:
            raise MediaUnreachableError(params={"url": url}) from exc
        return f"{self._base}/{key}"

    async def _download(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS),
                headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
                transport=self._transport,
            ) as client:
                current = url
                for _ in range(MAX_REDIRECTS + 1):
                    await self._check_host(current)
                    async with client.stream("GET", current) as response:
                        if response.is_redirect:
                            current = urljoin(current, response.headers["location"])
                            continue
                        return await self._read(response)
        except (httpx.HTTPError, OSError, KeyError, ValueError) as exc:
            raise MediaUnreachableError(params={"url": url}) from exc
        raise MediaUnreachableError(params={"url": url})

    async def _check_host(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("not https")
        if not _public(await self._resolve(parts.hostname)):
            raise ValueError("not a public host")

    @staticmethod
    async def _read(response: httpx.Response) -> bytes:
        if response.status_code != 200:
            raise ValueError(f"status {response.status_code}")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BYTES:
            raise ValueError("too large")
        buf = bytearray()
        async for chunk in response.aiter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("too large")
        return bytes(buf)


def build_media_mirror(settings: object) -> HttpS3MediaMirror:
    """Build the mirror from the application settings."""
    s3 = settings.s3  # type: ignore[attr-defined]
    put = S3Put(
        endpoint_url=s3.endpoint_url,
        region=s3.region,
        access_key=s3.access_key,
        secret_key=s3.secret_key.get_secret_value(),
        bucket=s3.bucket,
        acl=settings.admission.media_acl,  # type: ignore[attr-defined]
    )
    return HttpS3MediaMirror(put, f"{s3.public_endpoint_url.rstrip('/')}/{s3.bucket}")
