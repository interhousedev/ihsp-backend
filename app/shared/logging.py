"""structlog configuration shared by every process."""

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

REDACTED = "[Filtered]"
_SECRET_KEYS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
# Guest session, invitation and personal access tokens, wherever they show up.
_TOKEN = re.compile(r"(?<![A-Za-z0-9])((?:gst|inv|ihsp_pat)_)[A-Za-z0-9_\-]{16,}")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]+")
_AUTH_TEXT = re.compile(
    r"(?i)\b(authorization\s*[=:]\s*)[^\s,;\"']+(?:\s+[^\s,;\"']+)?"
)
# Admission and guest routes carry tokens and personal choices in the query string.
_ROUTE_QUERY = re.compile(
    r"((?:/v1)?/(?:admission|guest)(?:/[^\s?\"'#]*)?)\?[^\s\"'#]*"
)
_MAX_DEPTH = 8


def redact_text(text: str) -> str:
    """Mask tokens, bearer credentials and admission/guest query strings in text."""
    text = _ROUTE_QUERY.sub(lambda m: f"{m.group(1)}?{REDACTED}", text)
    text = _TOKEN.sub(lambda m: m.group(1) + REDACTED, text)
    text = _AUTH_TEXT.sub(lambda m: m.group(1) + REDACTED, text)
    return _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)


def _redact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and key.lower() in _SECRET_KEYS
                else _redact(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, depth + 1) for item in value)
    return value


def redact_secrets(_: object, __: str, event_dict: EventDict) -> EventDict:
    """Structlog processor: no credential or route query string reaches a log line.

    Covers `Authorization`/cookie keys and header text, `gst_`, `inv_` and
    `ihsp_pat_` tokens, and the query strings of `/admission` and `/guest` URLs, in
    the event, its bound values and nested dicts. Exception objects are left for the
    renderer (the second pass over the rendered traceback dicts catches their text).
    """
    return {
        key: (
            REDACTED
            if key.lower() in _SECRET_KEYS
            else (item if key == "exc_info" else _redact(item))
        )
        for key, item in event_dict.items()
    }


def _drop_color_message(_: object, __: str, event_dict: EventDict) -> EventDict:
    """Remove uvicorn's ANSI-colored copy of every message."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Route structlog and stdlib logging (uvicorn, sqlalchemy) to stdout."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        _drop_color_message,
        redact_secrets,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    json_post: list[Processor] = (
        [structlog.processors.dict_tracebacks, redact_secrets] if json_logs else []
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # The console renderer prints exc_info itself; it cannot take the dicts.
            *json_post,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers.clear()
        stdlib_logger.propagate = True
