"""ObjectStorage contract: the in-memory fake and the real S3 adapter must agree.

The S3 half runs against the compose S3 server (RustFS) with a fresh bucket.
"""

import base64
import hashlib
from collections.abc import AsyncIterator
from uuid import uuid4

from app.modules.files.infrastructure.s3.storage import (
    S3Storage,
    StorageError,
    content_disposition,
)
from app.modules.files.ports.storage import ObjectStorage
from app.settings import Settings
from tests.fakes.files.storage import InMemoryStorage

import httpx
import pytest
import pytest_asyncio


def _b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def _s3(settings: Settings, bucket: str, *, public: str | None = None) -> S3Storage:
    return S3Storage(
        endpoint_url=settings.s3.endpoint_url,
        public_endpoint_url=public or settings.s3.public_endpoint_url,
        region=settings.s3.region,
        access_key=settings.s3.access_key,
        secret_key=settings.s3.secret_key.get_secret_value(),
        bucket=bucket,
    )


@pytest_asyncio.fixture
async def real_storage(settings: Settings, s3_bucket: str) -> AsyncIterator[S3Storage]:
    """S3Storage on a fresh bucket of the compose S3 server."""
    storage = _s3(settings, s3_bucket)
    try:
        yield storage
    finally:
        await storage.close()


@pytest_asyncio.fixture(params=["memory", "s3"])
async def storage(
    request: pytest.FixtureRequest, settings: Settings, s3_bucket: str
) -> AsyncIterator[ObjectStorage]:
    """The same suite runs against both implementations."""
    if request.param == "memory":
        yield InMemoryStorage()
        return
    real = _s3(settings, s3_bucket)
    try:
        yield real
    finally:
        await real.close()


async def test_put_get_head_and_range(storage: ObjectStorage) -> None:
    """Write, read the whole object, read a range, ask for size and type."""
    key = f"contract/{uuid4()}.bin"
    data = bytes(range(256)) * 4

    await storage.put(key, data, "application/octet-stream")

    assert await storage.get(key) == data
    assert await storage.read_range(key, 0, 9) == data[:10]
    assert await storage.read_range(key, 1000, 5000) == data[1000:]
    info = await storage.head(key)
    assert info is not None
    assert info.size == len(data)


async def test_head_of_a_missing_object_is_none(storage: ObjectStorage) -> None:
    """A missing key is None, not an error."""
    assert await storage.head(f"contract/{uuid4()}") is None


async def test_delete_many_ignores_missing_keys_and_deletes_the_rest(
    storage: ObjectStorage,
) -> None:
    """DeleteObjects is idempotent."""
    keys = [f"contract/{uuid4()}" for _ in range(3)]
    for key in keys:
        await storage.put(key, b"x", "text/plain")

    await storage.delete_many([*keys, f"contract/{uuid4()}", keys[0]])

    for key in keys:
        assert await storage.head(key) is None
    await storage.delete_many([])


async def test_text_sidecar_content_type_is_stored(storage: ObjectStorage) -> None:
    """The sidecar is text/plain with an explicit charset."""
    key = f"contract/{uuid4()}.txt"

    await storage.put(key, "Привет".encode(), "text/plain; charset=utf-8")

    info = await storage.head(key)
    assert info is not None
    assert info.content_type is not None
    assert info.content_type.startswith("text/plain")


async def test_delete_many_sends_batches_of_at_most_1000_keys(
    real_storage: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DeleteObjects takes at most 1000 keys: the adapter batches (here 2 per call)."""
    from app.modules.files.infrastructure.s3 import storage as storage_module

    assert storage_module.DELETE_BATCH == 1000
    monkeypatch.setattr(storage_module, "DELETE_BATCH", 2)
    keys = [f"bulk/{uuid4()}/{index}" for index in range(5)]
    for key in keys:
        await real_storage.put(key, b"x", "text/plain")
    client = await real_storage._io()
    sizes: list[int] = []
    original = client.delete_objects

    async def recording(**kwargs: object) -> object:
        sizes.append(len(kwargs["Delete"]["Objects"]))  # type: ignore[index]
        return await original(**kwargs)

    monkeypatch.setattr(client, "delete_objects", recording)

    await real_storage.delete_many(keys)

    assert sizes == [2, 2, 1]
    for key in keys:
        assert await real_storage.head(key) is None


async def test_presigned_put_accepts_exactly_the_signed_upload(
    real_storage: S3Storage,
) -> None:
    """FILE-2: size, type and SHA-256 are signed; the right request works."""
    key = f"put/{uuid4()}.pdf"
    data = b"%PDF-1.4 hello presigned"

    upload = await real_storage.presign_put(
        key,
        content_type="application/pdf",
        content_length=len(data),
        sha256_b64=_b64(data),
    )
    async with httpx.AsyncClient() as client:
        response = await client.put(upload.url, content=data, headers=upload.headers)

    assert response.status_code == 200, response.text
    assert upload.method == "PUT"
    assert upload.headers == {
        "Content-Type": "application/pdf",
        "x-amz-checksum-sha256": _b64(data),
    }
    info = await real_storage.head(key)
    assert info is not None
    assert info.size == len(data)
    assert info.checksum_sha256 == _b64(data)
    assert await real_storage.get(key) == data


@pytest.mark.parametrize(
    "case",
    ["wrong_content_type", "no_checksum_header", "other_bytes", "longer_body"],
)
async def test_presigned_put_refuses_anything_that_differs_from_the_signature(
    real_storage: S3Storage, case: str
) -> None:
    """The server enforces the signed type, checksum header, checksum value and size."""
    key = f"put/{uuid4()}.pdf"
    data = b"%PDF-1.4 exact bytes"
    upload = await real_storage.presign_put(
        key,
        content_type="application/pdf",
        content_length=len(data),
        sha256_b64=_b64(data),
    )
    headers = dict(upload.headers)
    body = data
    if case == "wrong_content_type":
        headers["Content-Type"] = "text/html"
    elif case == "no_checksum_header":
        del headers["x-amz-checksum-sha256"]
    elif case == "other_bytes":
        body = b"%PDF-1.4 EXACT bytes"
    else:
        body = data + b"extra"

    async with httpx.AsyncClient() as client:
        response = await client.put(upload.url, content=body, headers=headers)

    assert response.status_code in {400, 403}, (case, response.status_code)
    assert await real_storage.head(key) is None


async def test_presigned_put_url_expires(real_storage: S3Storage) -> None:
    """The URL carries its lifetime (300 seconds by default)."""
    upload = await real_storage.presign_put(
        "put/expiry", content_type="text/plain", content_length=1, sha256_b64=_b64(b"x")
    )

    assert "X-Amz-Expires=300" in upload.url


async def test_presigned_get_sets_disposition_and_content_type(
    real_storage: S3Storage,
) -> None:
    """FILE-3: attachment or inline, a UTF-8 file name, the stored type."""
    key = f"get/{uuid4()}.pdf"
    await real_storage.put(key, b"%PDF-1.4 get me", "application/octet-stream")

    attachment = await real_storage.presign_get(
        key, filename="Отчёт 1.pdf", inline=False, content_type="application/pdf"
    )
    inline = await real_storage.presign_get(
        key, filename="report.pdf", inline=True, content_type="application/pdf"
    )
    async with httpx.AsyncClient() as client:
        first = await client.get(attachment)
        second = await client.get(inline)

    assert first.status_code == 200
    assert first.content == b"%PDF-1.4 get me"
    assert first.headers["content-type"] == "application/pdf"
    disposition = first.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82%201.pdf" in disposition
    assert second.headers["content-disposition"].startswith("inline;")
    assert 'filename="report.pdf"' in second.headers["content-disposition"]


async def test_presigned_urls_use_the_public_endpoint_host(
    settings: Settings, s3_bucket: str
) -> None:
    """URLs are signed for the public host; I/O goes to the internal one."""
    internal = settings.s3.endpoint_url
    public = internal.replace("localhost", "127.0.0.1")
    storage = _s3(settings, s3_bucket, public=public)
    key = f"host/{uuid4()}"
    try:
        await storage.put(key, b"hello host", "text/plain")

        url = await storage.presign_get(
            key, filename="a.txt", inline=False, content_type="text/plain"
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
    finally:
        await storage.close()

    assert url.startswith(public)
    assert response.status_code == 200
    assert response.content == b"hello host"


async def test_a_url_signed_for_one_host_fails_on_another(
    settings: Settings, s3_bucket: str
) -> None:
    """SigV4 signs the Host header: the signature is tied to the public host."""
    internal = settings.s3.endpoint_url
    public = internal.replace("localhost", "127.0.0.1")
    storage = _s3(settings, s3_bucket, public=public)
    key = f"host/{uuid4()}"
    try:
        await storage.put(key, b"hello host", "text/plain")
        url = await storage.presign_get(
            key, filename="a.txt", inline=False, content_type="text/plain"
        )
        wrong = url.replace("127.0.0.1", "localhost")
        async with httpx.AsyncClient() as client:
            response = await client.get(wrong)
    finally:
        await storage.close()

    assert response.status_code == 403


async def test_closing_twice_and_reusing_after_close_is_safe(
    settings: Settings, s3_bucket: str
) -> None:
    """The adapter reconnects lazily."""
    storage = _s3(settings, s3_bucket)
    key = f"close/{uuid4()}"
    await storage.put(key, b"x", "text/plain")
    await storage.close()
    await storage.close()

    assert await storage.head(key) is not None
    await storage.close()


def test_content_disposition_has_an_ascii_fallback_and_a_utf8_name() -> None:
    """RFC 5987: ``filename`` for old clients, ``filename*`` for the real name."""
    value = content_disposition('Отчёт "final".pdf', inline=False)

    assert value.startswith('attachment; filename="')
    assert '"final"' not in value.split("filename*")[0]
    assert "filename*=UTF-8''%D0%9E" in value
    assert content_disposition("a.png", inline=True).startswith("inline;")


async def test_a_delete_error_is_raised_as_storage_error(
    real_storage: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-key errors in a 200 response must not pass silently."""
    client = await real_storage._io()

    async def broken(**_: object) -> dict[str, object]:
        return {"Errors": [{"Key": "a", "Code": "AccessDenied"}]}

    monkeypatch.setattr(client, "delete_objects", broken)

    with pytest.raises(StorageError):
        await real_storage.delete_many(["a"])
