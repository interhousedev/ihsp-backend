"""S3 refusals (403) become the domain StorageError, never a bare 500."""

from typing import Any

from app.modules.files.domain.errors import StorageError
from app.modules.files.infrastructure.s3.storage import S3Storage

import pytest
import structlog
from botocore.exceptions import ClientError


def _client_error(code: str, status: int, op: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "denied"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        op,
    )


class _RefusingClient:
    """Stands in for the aiobotocore S3 client; every call is refused."""

    def __init__(self, code: str, status: int) -> None:
        self._code = code
        self._status = status

    def __getattr__(self, op: str) -> Any:
        async def refuse(**_: Any) -> None:
            raise _client_error(self._code, self._status, op)

        return refuse


def _storage(code: str, status: int) -> S3Storage:
    storage = S3Storage(
        endpoint_url="https://storage.cloupard.uz",
        public_endpoint_url="https://storage.cloupard.uz",
        region="us-east-1",
        access_key="ak",
        secret_key="sk",
        bucket="sp-files",
    )
    storage._client = _RefusingClient(code, status)
    return storage


@pytest.mark.parametrize("code,status", [("403", 403), ("AccessDenied", 403)])
async def test_head_forbidden_is_a_502_storage_error(code: str, status: int) -> None:
    """HeadObject 403 is an operator problem: 502 files/storage-unavailable."""
    storage = _storage(code, status)

    with pytest.raises(StorageError) as raised:
        await storage.head("student/a.pdf")

    assert raised.value.status == 502
    assert raised.value.code == "files/storage-unavailable"
    assert raised.value.support_details.startswith("s3 head refused")


async def test_head_404_still_means_missing() -> None:
    """A missing key stays None, so complete_upload answers upload-missing (409)."""
    assert await _storage("404", 404).head("student/a.pdf") is None


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.get("student/a.pdf"),
        lambda s: s.read_range("student/a.pdf", 0, 9),
        lambda s: s.put("student/a.pdf", b"x", "application/pdf"),
        lambda s: s.delete_many(["student/a.pdf"]),
    ],
)
async def test_other_io_refusals_map_to_storage_error(call: Any) -> None:
    """get/read/put/delete never leak a botocore ClientError to the HTTP layer."""
    storage = _storage("403", 403)

    with pytest.raises(StorageError) as raised:
        await call(storage)

    assert raised.value.status == 502


async def test_refusal_log_names_bucket_key_and_code() -> None:
    """The log has bucket, key and S3 code; no credentials or URLs."""
    storage = _storage("403", 403)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(StorageError):
            await storage.head("student/a.pdf")

    events = [entry for entry in logs if entry["event"] == "s3_request_refused"]
    assert events
    assert events[0]["bucket"] == "sp-files"
    assert events[0]["key"] == "student/a.pdf"
    assert events[0]["code"] == "403"
    assert "secret_key" not in events[0]
