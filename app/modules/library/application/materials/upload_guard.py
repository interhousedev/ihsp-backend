"""Who may upload now: no ban and within the daily and weekly limits (LIB-13)."""

from datetime import datetime
from uuid import UUID

from app.modules.library.domain.enums import UploaderRole
from app.modules.library.domain.errors import LibraryRateLimitedError, UploadBannedError
from app.modules.library.domain.moderation_rules import (
    UploadLimits,
    upload_windows,
    window_resets_at,
)
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.clock import Clock


class UploadGuard:
    """Counts submissions in the database, so the windows follow the injected clock."""

    def __init__(self, *, clock: Clock, limits: UploadLimits) -> None:
        """Store the clock and the limits of the settings."""
        self.clock = clock
        self.limits = limits

    async def ensure_not_banned(self, uow: LibraryUnitOfWork, user_id: UUID) -> None:
        """Raise `library/banned` while an upload ban is in force."""
        ban = await uow.moderation.active_ban(user_id, self.clock.now())
        if ban is not None:
            until = ban.until.isoformat() if ban.until else None
            raise UploadBannedError(params={"until": until})

    async def ensure_within_limits(
        self,
        uow: LibraryUnitOfWork,
        user_id: UUID,
        role: UploaderRole,
        *,
        exclude: UUID | None = None,
    ) -> None:
        """Raise `library/rate-limited` with `resets_at` when a window is full.

        `exclude` is the item being resubmitted: it must not count against itself.
        """
        now = self.clock.now()
        blocked: list[tuple[datetime, int]] = []
        for window in upload_windows(role, self.limits):
            times = await uow.moderation.upload_times(
                user_id, now - window.span, exclude=exclude
            )
            resets_at = window_resets_at(window, times)
            if resets_at is not None:
                blocked.append((resets_at, window.limit))
        if blocked:
            resets_at, limit = max(blocked)
            raise LibraryRateLimitedError(
                params={
                    "action": "upload",
                    "limit": limit,
                    "resets_at": resets_at.isoformat(),
                    "retry_after": max(int((resets_at - now).total_seconds()), 1),
                }
            )
