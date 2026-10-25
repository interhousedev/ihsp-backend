"""The refresh token cookie: HttpOnly, SameSite from settings, host-only (GEN-7)."""

from app.modules.identity.domain.client_policy import refresh_days
from app.settings import Settings

from fastapi import Request, Response

COOKIE_PATH = "/v1/oauth"
SECONDS_PER_DAY = 24 * 3600


def cookie_max_age(client_id: str) -> int:
    """Seconds the cookie lasts: the client's refresh lifetime (90 days for `app`)."""
    return refresh_days(client_id) * SECONDS_PER_DAY


def cookie_name(settings: Settings, client_id: str) -> str:
    """One cookie per client: rt_sp, rt_staff, ..."""
    return f"{settings.tokens.cookie_prefix}{client_id}"


def set_refresh_cookie(
    response: Response, settings: Settings, client_id: str, token: str
) -> None:
    """Store the (rotated) refresh token."""
    response.set_cookie(
        key=cookie_name(settings, client_id),
        value=token,
        max_age=cookie_max_age(client_id),
        path=COOKIE_PATH,
        secure=settings.tokens.refresh_cookie_secure,
        httponly=True,
        samesite=settings.tokens.refresh_cookie_samesite,
    )


def clear_refresh_cookie(
    response: Response, settings: Settings, client_id: str
) -> None:
    """Remove the cookie (same attributes, so the browser matches it)."""
    response.delete_cookie(
        key=cookie_name(settings, client_id),
        path=COOKIE_PATH,
        secure=settings.tokens.refresh_cookie_secure,
        httponly=True,
        samesite=settings.tokens.refresh_cookie_samesite,
    )


def read_refresh_cookie(
    request: Request, settings: Settings, client_id: str
) -> str | None:
    """The refresh token sent by the browser, if any."""
    return request.cookies.get(cookie_name(settings, client_id))
