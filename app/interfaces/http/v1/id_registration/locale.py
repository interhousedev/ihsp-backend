"""Choose the language of emails sent before the user has an account."""

from fastapi import Request

SUPPORTED = ("uz", "ru", "en")
DEFAULT = "ru"


def request_locale(request: Request) -> str:
    """Return the first supported language of ``Accept-Language`` (default ``ru``)."""
    for part in request.headers.get("accept-language", "").split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in SUPPORTED:
            return tag
    return DEFAULT
