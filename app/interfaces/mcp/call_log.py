"""Redaction of the MCP call log (B1): an allow-list, deny by default.

Kept parameters must be typed as ids, dates, numbers, booleans or enums; that is checked
when a tool registers, so a free-text parameter cannot be kept by mistake. Every other
string is stored as its length (no hash: short queries can be guessed from a hash), and
every list as its count. Card text, questions, file text and queries are never stored.
"""

import inspect
import re
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

_SCALARS: tuple[type, ...] = (UUID, date, datetime, int, float, bool)
_MAX_SUMMARY_IDS = 50
_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True, slots=True)
class LogSpec:
    """What of a call may be stored. A tool without a spec logs only its name."""

    keep: tuple[str, ...] = ()
    summarize: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None


def check_log_spec(tool: str, fn: Callable[..., Any], spec: LogSpec | None) -> None:
    """Refuse at registration a kept parameter that could hold free text."""
    if spec is None:
        return
    parameters = inspect.signature(fn).parameters
    for name in spec.keep:
        if name not in parameters:
            raise ValueError(f"{tool}: LogSpec keeps unknown parameter {name}")
        if not _is_safe(parameters[name].annotation):
            raise ValueError(f"{tool}: LogSpec may not keep free-text parameter {name}")


def _is_safe(annotation: Any) -> bool:  # noqa: ANN401 - any typing construct
    origin = get_origin(annotation)
    if origin is Annotated:
        return _is_safe(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        real = [a for a in get_args(annotation) if a is not type(None)]
        return bool(real) and all(_is_safe(a) for a in real)
    if origin is Literal:
        return True
    return isinstance(annotation, type) and issubclass(annotation, (*_SCALARS, Enum))


def redact_arguments(
    arguments: Mapping[str, Any], spec: LogSpec | None
) -> dict[str, Any] | None:
    """Return what may be stored of the arguments of a call."""
    if spec is None:
        return None
    stored: dict[str, Any] = {}
    for name, value in arguments.items():
        if value is not None:
            stored[name] = _kept(value) if name in spec.keep else _shape(value)
    return stored


def _kept(value: Any) -> Any:  # noqa: ANN401 - a validated tool argument
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if isinstance(value, date) else str(value)
    if isinstance(value, (bool, int, float, str)):
        return value  # a str here is a Literal, checked at registration
    return _shape(value)


def _shape(value: Any) -> dict[str, Any]:  # noqa: ANN401 - a validated tool argument
    if isinstance(value, str):
        return {"len": len(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {"count": len(value)}
    return {"present": True}


def summarize_result(
    result: Mapping[str, Any], spec: LogSpec | None
) -> dict[str, Any] | None:
    """Return counts, ids and status words of a result; never content or floats."""
    if spec is None or spec.summarize is None:
        return None
    try:
        summary = spec.summarize(result)
        return {
            str(key): clean
            for key, value in summary.items()
            if (clean := _summary_value(value)) is not None
        }
    except Exception:  # noqa: BLE001 - a trace never fails a call
        log.warning("mcp.call_log_summary_failed")
        return None


def _summary_value(value: Any) -> Any:  # noqa: ANN401 - whatever summarize returned
    if isinstance(value, bool | int):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return value if _is_uuid(value) or _TOKEN.match(value) else None
    if isinstance(value, list | tuple):
        ids = [str(item) for item in value if _is_uuid(str(item))]
        return ids[:_MAX_SUMMARY_IDS] or None
    return None


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
