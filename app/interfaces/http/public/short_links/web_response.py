"""Turning a WebResponse into an HTTP response with safe headers."""

from app.modules.links.application.views import WebResponse

from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse

PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def to_response(result: WebResponse) -> Response:
    """Map the use case answer to a redirect or an HTML page."""
    headers = dict(PUBLIC_HEADERS)
    if result.retry_after is not None:
        headers["Retry-After"] = str(result.retry_after)
    if result.location is not None:
        return RedirectResponse(
            result.location, status_code=result.status_code, headers=headers
        )
    return HTMLResponse(
        result.html or "", status_code=result.status_code, headers=headers
    )
