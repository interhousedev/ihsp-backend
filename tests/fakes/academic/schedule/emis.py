"""A scripted EmisSource for the schedule tests: bells and a student's classes."""

import datetime as dt
from uuid import UUID

from app.modules.identity.infrastructure.emis.fake import FAKE_CLASS_HOURS
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClass,
    EmisClassHour,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisUnavailable,
)


class FakeEmisSource:
    """Answers class hours and classes from scripted lists and records the calls."""

    def __init__(self) -> None:
        """Start with the real EMIS bells and no classes."""
        self.hours: list[EmisClassHour] = list(FAKE_CLASS_HOURS)
        self.classes: list[EmisClass] = []
        self.by_user: dict[UUID, list[EmisClass]] = {}
        self.calls: list[tuple[str, UUID]] = []
        self.hours_error: Exception | None = None
        self.timetable_error: Exception | None = None

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the scripted bells."""
        self.calls.append(("class_hours", user_id))
        if self.hours_error is not None:
            raise self.hours_error
        return list(self.hours)

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the scripted classes of the student that fall on begin..end."""
        self.calls.append(("timetable", user_id))
        if self.timetable_error is not None:
            raise self.timetable_error
        shown = self.by_user.get(user_id, self.classes)
        return [item for item in shown if begin <= item.date <= end]

    def down(self) -> None:
        """EMIS cannot be reached."""
        self.hours_error = self.timetable_error = EmisUnavailable()

    def rejects_credentials(self) -> None:
        """EMIS refuses the stored password."""
        self.hours_error = self.timetable_error = EmisAuthFailed()

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Not used by the schedule."""
        raise NotImplementedError

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Not used by the schedule."""
        raise NotImplementedError

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Not used by the schedule."""
        raise NotImplementedError
