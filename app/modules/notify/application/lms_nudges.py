"""Queue the LMS engagement nudges the learners opted in to.

The types are off by default: a learner turns each on in `preferences.lms_nudges`.
Nudges go out on weekdays outside the quiet hours (21:00-08:00 Tashkent) only, and
at most once per user, type and day (one per quest for `lms_deadline_soon`).
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any
from uuid import UUID

from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.clock import Clock, to_local
from app.shared.contracts.identity import IdentityDirectory, UserPreferences
from app.shared.contracts.lms_nudges import NudgeCandidate, NudgeCandidateSource
from app.shared.notifications import NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)

LMS_NUDGE_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.LMS_REVIEW_DUE,
        NotificationType.LMS_STREAK_AT_RISK,
        NotificationType.LMS_DEADLINE_SOON,
    }
)
QUIET_FROM = time(21, 0)
QUIET_UNTIL = time(8, 0)


def is_quiet(moment: datetime) -> bool:
    """True on weekends and from 21:00 to 08:00 Tashkent time."""
    local = to_local(moment)
    if local.weekday() >= 5:
        return True
    return not QUIET_UNTIL <= local.time() < QUIET_FROM


def nudge_dedupe_key(
    kind: NotificationType, user_id: UUID, day: str, payload: dict[str, Any]
) -> str:
    """`lms_nudge:<type>:<user>:<day>`, plus `:<quest_id>` for deadlines."""
    key = f"lms_nudge:{kind.value}:{user_id}:{day}"
    if kind == NotificationType.LMS_DEADLINE_SOON:
        key = f"{key}:{payload.get('quest_id', '')}"
    return key


@dataclass(slots=True)
class NudgeReport:
    """What one run did."""

    candidates: int = 0
    queued: int = 0
    opted_out: int = 0
    quiet: bool = False


class QueueLmsNudges:
    """Turns nudge candidates into notifications for the opted-in learners."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def execute(self, source: NudgeCandidateSource) -> NudgeReport:
        """Queue today's nudges; a rerun on the same day adds nothing new."""
        now = self.clock.now()
        report = NudgeReport()
        if is_quiet(now):
            report.quiet = True
            return report
        day = to_local(now).date()
        candidates = await source.list_nudge_candidates(day)
        report.candidates = len(candidates)
        prefs: dict[UUID, UserPreferences] = {}
        drafts: list[NotificationDraft] = []
        for candidate in candidates:
            draft = await self._draft(candidate, day.isoformat(), prefs)
            if draft is None:
                report.opted_out += 1
            else:
                drafts.append(draft)
        if drafts:
            async with self.uow_factory() as uow:
                uow.notify(*drafts)
                await uow.commit()
        report.queued = len(drafts)
        log.info("lms_nudges_queued", **asdict(report))
        return report

    async def _draft(
        self,
        candidate: NudgeCandidate,
        day: str,
        cache: dict[UUID, UserPreferences],
    ) -> NotificationDraft | None:
        try:
            kind = NotificationType(candidate.type)
        except ValueError:
            return None
        if kind not in LMS_NUDGE_TYPES:
            return None
        user_prefs = cache.get(candidate.user_id)
        if user_prefs is None:
            user_prefs = await self.identity.get_preferences(candidate.user_id)
            cache[candidate.user_id] = user_prefs
        if kind.value not in user_prefs.lms_nudges:
            return None
        return NotificationDraft(
            user_id=candidate.user_id,
            type=kind,
            payload=dict(candidate.payload),
            dedupe_key=nudge_dedupe_key(
                kind, candidate.user_id, day, candidate.payload
            ),
        )
