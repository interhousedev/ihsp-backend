"""Turning a WebResponse into an HTTP response with safe headers."""

from app.modules.links.application.views import WebResponse

from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse

PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def to_response(result: WebResponse, *, secure: bool = True) -> Response:
    """Map the use case answer to a redirect or an HTML page (plus its cookie)."""
    headers = dict(PUBLIC_HEADERS)
    if result.retry_after is not None:
        headers["Retry-After"] = str(result.retry_after)
    response: Response
    if result.location is not None:
        response = RedirectResponse(
            result.location, status_code=result.status_code, headers=headers
        )
    else:
        response = HTMLResponse(
            result.html or "", status_code=result.status_code, headers=headers
        )
    if result.cookie is not None:
        response.set_cookie(
            result.cookie.name,
            result.cookie.value,
            max_age=result.cookie.max_age,
            path=result.cookie.path,
            httponly=True,
            secure=secure,
            samesite="lax",
        )
    return response
