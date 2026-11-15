"""Maintenance mode: the platform is read-only while a server migration runs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.shared.base_error import BaseError


class MaintenanceError(BaseError):
    """A write was refused because the platform is in maintenance mode."""

    code = "common/maintenance"
    status = 503
    message_key = "error-maintenance"
    notify_user = False


@dataclass(frozen=True, slots=True)
class MaintenanceInfo:
    """What every web app may know (public): no host, no phase detail."""

    active: bool
    since: datetime | None = None
    moved: bool = False
    """The data is copied to the new server; this one stays read-only."""
    target_url: str | None = None


class MaintenanceGate(Protocol):
    """Answers, cheaply and for every request, whether writes are blocked."""

    def info(self) -> MaintenanceInfo:
        """The current maintenance state (cached for about a second)."""
        ...
