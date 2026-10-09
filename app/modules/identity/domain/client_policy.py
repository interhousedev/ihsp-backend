"""First-party OAuth clients: required roles and how long they stay signed in."""

from collections.abc import Iterable

from app.shared.actor import Role

FIRST_PARTY_CLIENTS = frozenset({"id", "sp", "staff", "admin", "lms", "app", "library"})
WEB_CLIENTS = FIRST_PARTY_CLIENTS
MINIAPP_CLIENT = "miniapp"
ADMIN_CLIENT = "admin"

DEFAULT_REFRESH_DAYS = 30
"""How long a browser on the websites stays signed in without a visit."""

LONG_SESSION_REFRESH_DAYS = 90
"""The installed app keeps people signed in longer: reopening it should not ask for
a password every month, as a home-screen app is opened less often than a website."""

LONG_SESSION_CLIENTS = frozenset({"app"})
"""Clients that get `LONG_SESSION_REFRESH_DAYS` instead of the default."""

_REQUIRED_ROLES: dict[str, frozenset[Role]] = {
    "staff": frozenset({Role.TEACHER}),
    "admin": frozenset({Role.ADMIN}),
    "library": frozenset({Role.STUDENT, Role.TEACHER, Role.LIBRARIAN, Role.ADMIN}),
}
"""Per client, the roles of which the person needs at least one (no entry: any)."""


def is_first_party(client_id: str) -> bool:
    """True for the first-party web platforms (the websites and the installed app)."""
    return client_id in FIRST_PARTY_CLIENTS


def may_use_client(client_id: str, roles: Iterable[Role]) -> bool:
    """True when the roles hold one of the roles the client requires (ID-16)."""
    required = _REQUIRED_ROLES.get(client_id)
    return required is None or bool(required & set(roles))


def refresh_days(client_id: str) -> int:
    """Days a refresh token (and its cookie) lasts: 90 for the installed app, else 30.

    The refresh cookie and the Hydra client lifespan must agree, or the cookie would
    outlive the token it holds (or the other way round).
    """
    if client_id in LONG_SESSION_CLIENTS:
        return LONG_SESSION_REFRESH_DAYS
    return DEFAULT_REFRESH_DAYS
