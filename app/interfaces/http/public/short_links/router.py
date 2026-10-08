"""Short link routes: `router` (dev, under /s) and `host_router` (host s.ihsu.uz)."""

from app.interfaces.http.public.robots.router import robots
from app.interfaces.http.public.short_links.handlers.open_short_link import (
    open_short_link,
)
from app.interfaces.http.public.short_links.handlers.report_form import (
    show_report_form,
    submit_report_form,
)

from fastapi import APIRouter


def _register(target: APIRouter) -> None:
    target.add_api_route(
        "/{slug}/report", show_report_form, methods=["GET"], include_in_schema=False
    )
    target.add_api_route(
        "/{slug}/report", submit_report_form, methods=["POST"], include_in_schema=False
    )
    target.add_api_route(
        "/{slug}", open_short_link, methods=["GET"], include_in_schema=False
    )


router = APIRouter(prefix="/s")
_register(router)

host_router = APIRouter()
host_router.add_api_route(
    "/robots.txt", robots, methods=["GET"], include_in_schema=False
)
_register(host_router)
