"""HTML widget routes of the learner player: launch URL and the widget's files."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.html_widget_links import WidgetFileNotFound
from app.modules.lms.application.learning.views import HtmlWidgetLaunchView
from app.modules.lms.domain.html_widget import WIDGET_TOKEN_SECONDS
from app.settings import Settings
from app.shared.actor import Actor

from fastapi import Depends, Response

# Widget files never change (a new upload is a new widget): cache them for the
# token's lifetime, in the browser only.
WIDGET_FILE_CACHE = f"private, max-age={WIDGET_TOKEN_SECONDS}"


def widget_policy(settings: Settings) -> str:
    """Return the CSP of every widget response.

    The document runs sandboxed (opaque origin, scripts only: no popups, so it
    cannot open a window to carry data out or show a fake login), loads nothing
    but its own files and inline code, connects nowhere, submits no form and may
    be framed only by the LMS.
    """
    ancestors = settings.urls.lms.rstrip("/")
    return (
        "sandbox allow-scripts; "
        "default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob: data:; "
        "connect-src 'none'; "
        "form-action 'none'; "
        f"frame-ancestors {ancestors}; "
        "base-uri 'none'"
    )


def widget_headers(settings: Settings) -> dict[str, str]:
    """Return the headers sent with every widget response, errors included."""
    return {
        "Content-Security-Policy": widget_policy(settings),
        "X-Content-Type-Options": "nosniff",
        # The sandboxed document has an opaque origin, which is never same-site:
        # same-site would block its own scripts and images. The token gates access.
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Referrer-Policy": "no-referrer",
        # The sandboxed frame has an opaque origin; module scripts are CORS
        # requests. The files carry no credentials: the token in the path is the
        # access, so the wildcard grants nothing more than the link itself.
        "Access-Control-Allow-Origin": "*",
    }


async def get_html_widget_launch(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> HtmlWidgetLaunchView:
    """Return the signed URL of the block's widget (enrolled or staff)."""
    response.headers["Cache-Control"] = "no-store"
    learning = container.lms.learning
    view: HtmlWidgetLaunchView = await learning.get_html_widget_launch.execute(
        actor, course_id, step_id, block_id
    )
    return view


async def get_html_widget_file(
    token: str,
    path: str,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Serve one file of a widget; the signed token in the path is the access."""
    headers = widget_headers(container.settings)
    try:
        file = await container.lms.learning.html_widget_links.read(token, path)
    except WidgetFileNotFound:
        headers["Cache-Control"] = "no-store"
        return Response(
            b"Not found", status_code=404, media_type="text/plain", headers=headers
        )
    headers["Cache-Control"] = WIDGET_FILE_CACHE
    return Response(file.data, media_type=file.content_type, headers=headers)
