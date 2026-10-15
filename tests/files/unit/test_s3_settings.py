"""S3 endpoint/bucket config fails fast with guidance, not a 500 at upload."""

from app.settings import S3Settings

import pydantic
import pytest


def _s3(**overrides: str) -> S3Settings:
    values = {
        "endpoint_url": "https://storage.cloupard.uz",
        "public_endpoint_url": "https://storage.cloupard.uz",
        "bucket": "sp-files",
    }
    values.update(overrides)
    return S3Settings(**values)


def test_scheme_and_host_with_matching_endpoints_is_accepted() -> None:
    """The Cloupard setting: both endpoints are the bare host, bucket separate."""
    settings = _s3()
    assert settings.endpoint_url == "https://storage.cloupard.uz"
    assert settings.bucket == "sp-files"


def test_trailing_slash_on_an_origin_is_fine() -> None:
    """A trailing slash is not a path segment."""
    assert _s3(endpoint_url="https://storage.cloupard.uz/").endpoint_url.endswith("/")


@pytest.mark.parametrize(
    "endpoint",
    ["https://storage.cloupard.uz/ihsp", "https://storage.cloupard.uz/sp-files/"],
)
def test_endpoint_with_a_path_is_rejected_with_guidance(endpoint: str) -> None:
    """A path in the endpoint makes presigned and HEAD keys diverge: refuse it."""
    with pytest.raises(pydantic.ValidationError) as raised:
        _s3(endpoint_url=endpoint, public_endpoint_url=endpoint)
    message = str(raised.value)
    assert "must be scheme://host only" in message
    assert "S3__BUCKET" in message


def test_public_and_internal_endpoints_must_agree_in_path() -> None:
    """Internal host without a path and public host with one is a config error."""
    with pytest.raises(pydantic.ValidationError) as raised:
        _s3(
            endpoint_url="https://storage.cloupard.uz",
            public_endpoint_url="https://storage.cloupard.uz/ihsp",
        )
    assert "scheme://host only" in str(raised.value)


def test_bucket_with_a_slash_is_rejected() -> None:
    """The bucket is a bare name; a slash means a path was put in the wrong place."""
    with pytest.raises(pydantic.ValidationError) as raised:
        _s3(bucket="ihsp/student")
    assert "bare bucket name" in str(raised.value)


def test_non_http_endpoint_is_rejected() -> None:
    """Only http(s) endpoints with a host are valid."""
    with pytest.raises(pydantic.ValidationError):
        _s3(endpoint_url="storage.cloupard.uz")
