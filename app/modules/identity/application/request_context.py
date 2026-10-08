"""Who is calling: client IP and user agent, normalised for storage."""

import ipaddress
from dataclasses import dataclass

from app.modules.identity.domain.session import UNKNOWN_IP

MAX_USER_AGENT = 512


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Client address and device of the current request."""

    ip: str | None = None
    user_agent: str | None = None

    @property
    def valid_ip(self) -> str | None:
        """The IP if it parses, else None."""
        if not self.ip:
            return None
        try:
            return str(ipaddress.ip_address(self.ip))
        except ValueError:
            return None

    @property
    def throttle_ip(self) -> str:
        """Key for per-IP counters."""
        return self.valid_ip or "unknown"

    @property
    def session_ip(self) -> str:
        """Value for the inet column of a session."""
        return self.valid_ip or UNKNOWN_IP

    @property
    def device(self) -> str:
        """User agent trimmed for storage."""
        return (self.user_agent or "")[:MAX_USER_AGENT]
