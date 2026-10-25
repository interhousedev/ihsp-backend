"""Feedback attachments: an explicit MIME allowlist, no prefix matches."""

from app.modules.feedback.domain.attachments import allowed_type

import pytest


@pytest.mark.parametrize(
    "content_type",
    [
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ],
)
def test_listed_types_are_allowed(content_type: str) -> None:
    assert allowed_type(content_type)


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "text/javascript",
        "text/markdown",
        "image/svg+xml",
        "video/x-msvideo",
        "image/heic",
        "application/octet-stream",
        "application/x-msdownload",
        "application/zip",
    ],
)
def test_other_types_under_the_old_prefixes_are_refused(content_type: str) -> None:
    assert not allowed_type(content_type)
