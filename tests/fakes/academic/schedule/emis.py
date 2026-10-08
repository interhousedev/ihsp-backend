"""A scripted EmisSource for the schedule tests: bells and a group's timetable."""

from uuid import UUID

from app.modules.identity.infrastructure.emis.fake import FAKE_CLASS_HOURS
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClassHour,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisTimetableItem,
    EmisUnavailable,
)


class FakeEmisSource:
    """Answers class hours and timetable from scripted lists and records the calls."""

    def __init__(self) -> None:
        """Start with the real EMIS bells and an empty timetable."""
        self.hours: list[EmisClassHour] = list(FAKE_CLASS_HOURS)
        self.items: list[EmisTimetableItem] = []
        self.calls: list[tuple[str, UUID]] = []
        self.hours_error: Exception | None = None
        self.timetable_error: Exception | None = None

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the scripted bells."""
        self.calls.append(("class_hours", user_id))
        if self.hours_error is not None:
            raise self.hours_error
        return list(self.hours)

    async def timetable(self, user_id: UUID) -> list[EmisTimetableItem]:
        """Return the scripted timetable."""
        self.calls.append(("timetable", user_id))
        if self.timetable_error is not None:
            raise self.timetable_error
        return list(self.items)

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
