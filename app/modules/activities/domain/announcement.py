"""Club announcements. The system picks the delivery channel, never the sender."""

import html
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from uuid import UUID, uuid4

from app.modules.activities.domain.errors import Conflict, Invalid

__all__ = [
    "DAILY_LIMIT",
    "Announcement",
    "AnnouncementInvalidError",
    "AnnouncementLimitError",
    "AnnouncementStateError",
    "check_daily_limit",
    "parse_audience",
    "sanitize_html",
]

DAILY_LIMIT = 3
_SIMPLE = {"b", "i", "u", "s", "code", "pre"}
_DROP_CONTENT = {"script", "style"}


class AnnouncementInvalidError(Invalid):
    """The announcement is malformed."""


class AnnouncementLimitError(Conflict):
    """The club hit its daily announcement limit."""


class AnnouncementStateError(Conflict):
    """The announcement was already sent or cancelled."""


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.skip_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        if tag in _SIMPLE:
            self.out.append(f"<{tag}>")
            self.open.append(tag)
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("https://"):
                self.out.append(f'<a href="{html.escape(href, quote=True)}">')
                self.open.append("a")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif tag in self.open:
            while self.open:
                top = self.open.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def sanitize_html(text: str) -> str:
    """Keep only b, i, u, s, code, pre and https links (the Telegram subset)."""
    parser = _Cleaner()
    parser.feed(text)
    parser.close()
    while parser.open:
        parser.out.append(f"</{parser.open.pop()}>")
    return "".join(parser.out)


def parse_audience(value: str) -> tuple[str, UUID | None]:
    """`members`, `team` or `event:<uuid>`."""
    if value in ("members", "team"):
        return value, None
    if value.startswith("event:"):
        try:
            return "event", UUID(value[len("event:") :])
        except ValueError:
            pass
    raise AnnouncementInvalidError(params={"field": "audience"})


def check_daily_limit(sent_today: int, *, is_staff: bool) -> None:
    """Non-staff clubs may send `DAILY_LIMIT` announcements a day."""
    if not is_staff and sent_today >= DAILY_LIMIT:
        raise AnnouncementLimitError(params={"limit": DAILY_LIMIT})


@dataclass(slots=True)
class Announcement:
    """A message from the club to a part of its people."""

    club_id: UUID
    author_id: UUID
    text: str
    audience: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    recipient_count: int = 0
    cancelled: bool = False

    @classmethod
    def compose(
        cls,
        *,
        club_id: UUID,
        author_id: UUID,
        text: str,
        audience: str,
        now: datetime | None = None,
    ) -> "Announcement":
        """Clean the text and check the audience."""
        parse_audience(audience)
        clean = sanitize_html(text)
        if not clean.strip():
            raise AnnouncementInvalidError(params={"field": "text"})
        return cls(club_id, author_id, clean, audience, created_at=now)

    def schedule(self, at: datetime, now: datetime) -> None:
        """Send later."""
        if at <= now:
            raise AnnouncementInvalidError(params={"field": "scheduled_at"})
        self.scheduled_at = at

    def _open(self) -> None:
        if self.sent_at is not None or self.cancelled:
            raise AnnouncementStateError()

    def cancel(self) -> None:
        """Cancel before sending."""
        self._open()
        self.cancelled = True

    def mark_sent(self, now: datetime, recipients: int) -> None:
        """Record the send."""
        self._open()
        self.sent_at = now
        self.recipient_count = recipients
