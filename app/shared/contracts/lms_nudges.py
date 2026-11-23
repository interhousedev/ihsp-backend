"""LMS engagement nudges (provider: lms engagement; consumer: notify via the job)."""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID


class NudgeCandidate(Protocol):
    """One nudge for one learner.

    Types: `lms_review_due` `{count}`, `lms_streak_at_risk` `{streak}` and
    `lms_deadline_soon` `{quest_id, title, ends_on}`.
    """

    @property
    def user_id(self) -> UUID:
        """The learner."""
        ...

    @property
    def type(self) -> str:
        """The notification type value."""
        ...

    @property
    def payload(self) -> dict[str, Any]:
        """The notification payload."""
        ...


class NudgeCandidateSource(Protocol):
    """Lists who should be nudged on a Tashkent day (read-only)."""

    async def list_nudge_candidates(self, day: dt.date) -> Sequence[NudgeCandidate]:
        """Return the candidates of the day; preferences are checked by the caller."""
        ...
