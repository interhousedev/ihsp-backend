"""Use case: the iCal feed behind a secret token (WEB-6)."""

from app.interfaces.http.v1.composition.application.render_ical import render_calendar
from app.interfaces.http.v1.composition.application.views import load_users
from app.interfaces.http.v1.composition.errors import CalendarFeedNotFoundError
from app.interfaces.http.v1.composition.ports import (
    CalendarTokenStore,
    ScheduleOverview,
)
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import hash_token

# Tokens are 256-bit URL-safe strings; anything else cannot be a real token.
MIN_TOKEN_LENGTH = 16
MAX_TOKEN_LENGTH = 128


class BuildCalendarFeed:
    """Renders the student's lessons of the whole term, projected from the timetable."""

    def __init__(
        self,
        *,
        tokens: CalendarTokenStore,
        overview: ScheduleOverview,
        schedule: ScheduleQueries,
        identity: IdentityDirectory,
        clock: Clock,
        calendar_name: str,
    ) -> None:
        """Store the collaborators; `calendar_name` titles the calendar."""
        self.tokens = tokens
        self.overview = overview
        self.schedule = schedule
        self.identity = identity
        self.clock = clock
        self.calendar_name = calendar_name

    async def execute(self, token: str) -> bytes:
        """Return the `.ics` bytes or raise `CalendarFeedNotFoundError`."""
        if not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH:
            raise CalendarFeedNotFoundError()
        user_id = await self.tokens.user_for_token(hash_token(token))
        if user_id is None:
            raise CalendarFeedNotFoundError()
        bounds = await self.overview.term_bounds(local_today(self.clock))
        lessons: list[LessonRef] = []
        if bounds is not None:
            lessons = await self.schedule.projected_lessons_for_student(
                user_id, bounds[0], bounds[1]
            )
        teachers = await load_users(
            self.identity, [x.teacher_id for x in lessons if x.teacher_id is not None]
        )
        return render_calendar(
            lessons, teachers, name=self.calendar_name, now=self.clock.now()
        )
