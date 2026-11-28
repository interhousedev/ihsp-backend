"""Event reminder planning."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.activities.domain.event import Event, EventStatus
from app.shared.notifications import NotificationDraft, NotificationType

__all__ = [
    "REMINDER_OFFSETS",
    "dedupe_key",
    "plan_reminders",
    "rating_request_time",
    "reminder_prefix",
]

REMINDER_OFFSETS = (60, 15, 5)
RATING_DELAY = timedelta(hours=2)


def reminder_prefix(event_id: UUID) -> str:
    """Prefix shared by every reminder of the event."""
    return f"activities:event:{event_id}:"


def dedupe_key(event_id: UUID, revision: int, offset: int, user_id: UUID) -> str:
    """The revision keeps a post-reschedule reminder from colliding with a sent one."""
    return f"{reminder_prefix(event_id)}r{revision}:{offset}:{user_id}"


def rating_request_time(event: Event) -> datetime:
    """When attendees are asked to rate the event."""
    return event.ends_at + RATING_DELAY


def plan_reminders(
    event: Event, participants: list[UUID], organizers: list[UUID], now: datetime
) -> list[NotificationDraft]:
    """Reminders still in the future; organizers win when a person is in both lists."""
    if event.status != EventStatus.SCHEDULED:
        return []
    orgs = list(dict.fromkeys(organizers))
    parts = [p for p in dict.fromkeys(participants) if p not in set(orgs)]
    headcount = len(set(participants))
    drafts: list[NotificationDraft] = []
    for role, users in (("organizer", orgs), ("participant", parts)):
        for user in users:
            for offset in REMINDER_OFFSETS:
                at = event.starts_at - timedelta(minutes=offset)
                if at <= now:
                    continue
                payload: dict[str, object] = {
                    "event_id": str(event.id),
                    "club_id": str(event.club_id),
                    "title": event.title,
                    "starts_at": event.starts_at.isoformat(),
                    "offset": offset,
                    "role": role,
                }
                if role == "organizer":
                    payload["headcount"] = headcount
                    payload["check_in_link"] = f"/activities/events/{event.id}/check-in"
                drafts.append(
                    NotificationDraft(
                        user_id=user,
                        type=NotificationType.EVENT_REMINDER,
                        payload=payload,
                        dedupe_key=dedupe_key(
                            event.id, event.schedule_revision, offset, user
                        ),
                        scheduled_at=at,
                    )
                )
    return drafts
