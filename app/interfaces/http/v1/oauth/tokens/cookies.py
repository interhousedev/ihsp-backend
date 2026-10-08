"""The refresh token cookie: HttpOnly, SameSite=Strict, host-only (GEN-7)."""

from app.settings import Settings

from fastapi import Request, Response

COOKIE_PATH = "/v1/oauth"
COOKIE_MAX_AGE = 30 * 24 * 3600


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
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        secure=settings.tokens.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
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
        samesite="strict",
    )


def read_refresh_cookie(
    request: Request, settings: Settings, client_id: str
) -> str | None:
    """The refresh token sent by the browser, if any."""
    return request.cookies.get(cookie_name(settings, client_id))
