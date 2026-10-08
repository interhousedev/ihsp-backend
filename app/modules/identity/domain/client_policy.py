"""Which roles each first-party OAuth client requires."""

from collections.abc import Iterable

from app.shared.actor import Role

FIRST_PARTY_CLIENTS = frozenset({"id", "sp", "staff", "admin", "lms"})
WEB_CLIENTS = FIRST_PARTY_CLIENTS
MINIAPP_CLIENT = "miniapp"
ADMIN_CLIENT = "admin"

_REQUIRED_ROLE: dict[str, Role] = {
    "staff": Role.TEACHER,
    "admin": Role.ADMIN,
}


def is_first_party(client_id: str) -> bool:
    """True for the five web platforms."""
    return client_id in FIRST_PARTY_CLIENTS


def may_use_client(client_id: str, roles: Iterable[Role]) -> bool:
    """True when the roles satisfy what the client requires (ID-16)."""
    required = _REQUIRED_ROLE.get(client_id)
    return required is None or required in set(roles)


def requires_recent_mfa(client_id: str) -> bool:
    """The admin platform accepts only recent password + OTP logins (ID-11)."""
    return client_id == ADMIN_CLIENT
