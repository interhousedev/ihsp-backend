"""Secret iCal feed tokens of students (WEB-6): rotate one, find its owner."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory


class RotateCalendarToken:
    """Replace the stored token hash of a student; the old feed URL stops working."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(self, user_id: UUID, token_hash: str) -> bool:
        """Store the SHA-256 of the new token; False when the user is no student."""
        async with self.uow_factory() as uow:
            stored = await uow.students.set_calendar_token_hash(user_id, token_hash)
            if stored:
                await uow.commit()
        return stored


class UserForCalendarToken:
    """Find the active student that owns a token hash."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(self, token_hash: str) -> UUID | None:
        """Return the owner of the hash, or None for an unknown or left student."""
        async with self.uow_factory() as uow:
            return await uow.students.user_id_for_calendar_token(token_hash)
