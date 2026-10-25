"""Presigned URLs are SigV4 for every S3 client the app builds (no SigV2 query auth)."""

from urllib.parse import parse_qs, urlsplit

from app.modules.files.infrastructure.s3.storage import S3Storage

import pytest

PUBLIC = "https://storage.cloupard.uz"
INTERNAL = "http://s3:9000"
SHA = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="


def _storage(region: str = "us-east-1") -> S3Storage:
    return S3Storage(
        endpoint_url=INTERNAL,
        public_endpoint_url=PUBLIC,
        region=region,
        access_key="AKIATESTONLY",
        secret_key="test-secret-only",
        bucket="sp-files",
    )


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


@pytest.mark.asyncio
async def test_presigned_get_is_sigv4() -> None:
    """GET URLs carry the SigV4 algorithm, not AWSAccessKeyId/Signature."""
    storage = _storage()
    try:
        url = await storage.presign_get(
            "system/2026-10/file.pdf",
            filename="file.pdf",
            inline=True,
            content_type="application/pdf",
        )
    finally:
        await storage.close()
    query = _query(url)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "AWSAccessKeyId" not in query
    assert "Signature" not in query
    assert urlsplit(url).netloc == "storage.cloupard.uz"
    assert urlsplit(url).path == "/sp-files/system/2026-10/file.pdf"


@pytest.mark.asyncio
async def test_presigned_put_is_sigv4() -> None:
    """PUT URLs carry the SigV4 algorithm and the region-scoped credential."""
    storage = _storage(region="eu-west-1")
    try:
        upload = await storage.presign_put(
            "system/2026-10/new.pdf",
            content_type="application/pdf",
            content_length=10,
            sha256_b64=SHA,
        )
    finally:
        await storage.close()
    query = _query(upload.url)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "AWSAccessKeyId" not in query
    assert query["X-Amz-Credential"][0].split("/")[2] == "eu-west-1"
    assert urlsplit(upload.url).netloc == "storage.cloupard.uz"
