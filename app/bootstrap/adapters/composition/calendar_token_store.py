"""CalendarTokenStore over the academic schedule's calendar token use cases."""

from uuid import UUID

from app.modules.academic.application.schedule.calendar_token import (
    RotateCalendarToken,
    UserForCalendarToken,
)


class CalendarTokenStoreAdapter:
    """Composition <- academic: secret iCal feed tokens (only their SHA-256)."""

    def __init__(
        self,
        rotate_calendar_token: RotateCalendarToken,
        user_for_calendar_token: UserForCalendarToken,
    ) -> None:
        """Keep the two schedule use cases."""
        self._rotate = rotate_calendar_token
        self._user_for_token = user_for_calendar_token

    async def rotate(self, user_id: UUID, token_hash: str) -> bool:
        """Replace the student's token hash; False when the user has no student row."""
        return await self._rotate.execute(user_id, token_hash)

    async def user_for_token(self, token_hash: str) -> UUID | None:
        """Return the active student that owns the token hash."""
        return await self._user_for_token.execute(token_hash)
