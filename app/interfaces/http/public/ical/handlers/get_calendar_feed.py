"""GET /ical/{token}.ics."""

from typing import Annotated

from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.services import Composition

from fastapi import Depends, Response

CACHE_CONTROL = "max-age=900"


class CalendarResponse(Response):
    """An iCalendar document."""

    media_type = "text/calendar"


async def get_calendar_feed(
    token: str, composition: Annotated[Composition, Depends(get_composition)]
) -> CalendarResponse:
    """Return the student's lessons for the whole term as an iCalendar feed."""
    content = await composition.build_calendar_feed.execute(token)
    return CalendarResponse(content, headers={"Cache-Control": CACHE_CONTROL})
