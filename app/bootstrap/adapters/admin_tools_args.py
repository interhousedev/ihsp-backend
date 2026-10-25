"""Reading tool arguments: the AI catalog and the MCP servers name them differently."""

import datetime as dt
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from app.shared.base_error import ValidationFailedError
from app.shared.clock import TASHKENT

from pydantic import BaseModel, ValidationError

Args = Mapping[str, Any]
M = TypeVar("M", bound=BaseModel)


def invalid(reason: str) -> ValidationFailedError:
    """A tool call with unusable arguments."""
    return ValidationFailedError(params={"reason": reason}, support_details=reason)


def validate(model: type[M], data: Args) -> M:
    """Validate arguments against an HTTP request body model."""
    try:
        return model.model_validate(dict(data))
    except ValidationError as exc:
        raise invalid(str(exc.errors(include_url=False)[:3])) from exc


def uuid_arg(args: Args, name: str) -> UUID:
    """A required UUID argument."""
    try:
        return UUID(str(args[name]))
    except (KeyError, ValueError) as exc:
        raise invalid(f"{name} must be a UUID") from exc


def opt_uuid(args: Args, name: str) -> UUID | None:
    """An optional UUID argument; empty strings count as not sent."""
    value = args.get(name)
    if value in (None, ""):
        return None
    return uuid_arg(args, name)


def opt_date(args: Args, *names: str) -> dt.date | None:
    """An optional date under any of the names (`from` or `date_from`)."""
    for name in names:
        value = args.get(name)
        if value not in (None, ""):
            try:
                return dt.date.fromisoformat(str(value))
            except ValueError as exc:
                raise invalid(f"{name} must be YYYY-MM-DD") from exc
    return None


def day_start(day: dt.date | None) -> dt.datetime | None:
    """Midnight of a Tashkent day, as an aware datetime."""
    return dt.datetime.combine(day, dt.time.min, tzinfo=TASHKENT) if day else None


def day_end(day: dt.date | None) -> dt.datetime | None:
    """Midnight after a Tashkent day (exclusive end of the day)."""
    return day_start(day + dt.timedelta(days=1)) if day else None


def limit_arg(args: Args, default: int, maximum: int) -> int:
    """A page size clamped to 1..maximum."""
    try:
        value = int(args.get("limit") or default)
    except (TypeError, ValueError) as exc:
        raise invalid("limit must be a number") from exc
    return max(1, min(value, maximum))
