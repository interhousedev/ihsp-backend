"""Nudge events of the engagement features.

The notify cron task `lms.engagement_nudges` reads them through
`list_nudge_candidates` and writes them to the outbox once per user and Tashkent
day (dedupe key `lms_nudge:<type>:<user_id>:<YYYY-MM-DD>[:<quest_id>]`; opt-in
and the weekday 08:00-21:00 window apply there). Event types and payloads:

- `lms_review_due` `{count}`: review questions are due;
- `lms_streak_at_risk` `{streak}`: a weekday with no activity yet and a running streak;
- `lms_deadline_soon` `{quest_id, title, ends_on}`: a class quest ends today or
  tomorrow and the learner has not reached its target.
"""

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

REVIEW_DUE: Final = "lms_review_due"
STREAK_AT_RISK: Final = "lms_streak_at_risk"
DEADLINE_SOON: Final = "lms_deadline_soon"


@dataclass(frozen=True, slots=True)
class Nudge:
    """One nudge for one learner."""

    user_id: UUID
    type: str
    payload: dict[str, Any]
