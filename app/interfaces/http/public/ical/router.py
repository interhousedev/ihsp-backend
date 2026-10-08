"""Route of the secret iCal feed."""

from app.interfaces.http.public.ical.handlers.get_calendar_feed import (
    CalendarResponse,
    get_calendar_feed,
)

from fastapi import APIRouter

router = APIRouter(tags=["composition"])
router.add_api_route(
    "/ical/{token}.ics",
    get_calendar_feed,
    methods=["GET"],
    response_class=CalendarResponse,
)
