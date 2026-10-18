"""Error tracking to Bugsink (Sentry protocol), one init per process.

Off unless `IHSP_BUGSINK__DSN` is set. PII stays out: `send_default_pii` is False and
`before_send` drops auth headers, cookies and anything that looks like a secret.
"""

import logging
import re
from typing import TYPE_CHECKING, Any

from app.settings import Settings

if TYPE_CHECKING:
    from sentry_sdk._types import Event

SCRUBBED = "[Filtered]"
_SECRET_KEY = re.compile(
    r"(authorization|cookie|token|secret|password|api[_-]?key|session|csrf)", re.I
)
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}
_initialized = False


def _scrub_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: SCRUBBED if _SECRET_KEY.search(str(key)) else _scrub_mapping(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_scrub_mapping(item) for item in data]
    return data


def scrub_event(event: "Event", _hint: dict[str, Any]) -> "Event":
    """Strip auth headers, cookies and secret-looking keys from an outgoing event."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: SCRUBBED if key.lower() in _SENSITIVE_HEADERS else value
                for key, value in headers.items()
            }
        request.pop("cookies", None)
        request.pop("query_string", None)
    event.pop("user", None)
    for section in ("extra", "contexts", "tags"):
        if section in event:
            event[section] = _scrub_mapping(event[section])
    return event


def init_observability(settings: Settings, process: str) -> bool:
    """Start the Sentry client against Bugsink for this process. Returns True if on."""
    global _initialized
    dsn = settings.bugsink.dsn.strip()
    if not dsn or _initialized:
        return bool(dsn)

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    release = settings.bugsink.release or None
    sentry_sdk.init(
        dsn=dsn,
        release=release,
        environment=settings.env,
        send_default_pii=False,
        traces_sample_rate=settings.bugsink.traces_sample_rate,
        before_send=scrub_event,
        integrations=[
            LoggingIntegration(
                level=None,  # breadcrumbs: INFO and up
                event_level=logging.WARNING,  # events: WARNING and above
            )
        ],
    )
    sentry_sdk.set_tag("process", process)
    _initialized = True
    return True
