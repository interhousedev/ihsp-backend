"""Topic labels of sources: entities, name rules and the limits (spec 3.4, G12/G13).

A notebook has up to 12 labels; a source carries up to 3. A label is `auto` when the
model proposed it and `manual` when the student made or edited it. A link between a
source and a label has its own origin: an `auto` run replaces only `auto` links.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

LABEL_NAME_MAX_CHARS: Final = 40
LABEL_EMOJI_MAX_CHARS: Final = 8
DEFAULT_LABEL_EMOJI: Final = "🏷️"
MAX_LABELS: Final = 12  # per notebook
MAX_LABELS_PER_SOURCE: Final = 3  # by hand
AUTO_LABELS_PER_SOURCE: Final = 2  # what one auto run gives a source
STUCK_LABELING_MINUTES: Final = 10  # a run this old is treated as dead
SOURCE_LABELS_RUN_TASK: Final = "notebooks.label_sources"

# Why an auto run failed (`LabelRun.error`, a stable code for the web app).
ERROR_NOTHING_TO_LABEL: Final = "nothing-to-label"
ERROR_PROVIDER: Final = "provider"
ERROR_INVALID_OUTPUT: Final = "invalid-output"
ERROR_LIMIT_REACHED: Final = "limit-reached"
ERROR_TIMEOUT: Final = "timeout"


class LabelOrigin(StrEnum):
    """Who made a label or a link: the model (`auto`) or the student (`manual`)."""

    AUTO = "auto"
    MANUAL = "manual"


class LabelRunStatus(StrEnum):
    """State of the automatic labeling of a notebook."""

    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(slots=True)
class SourceLabel:
    """A topic label of a notebook."""

    id: UUID
    notebook_id: UUID
    name: str
    emoji: str
    position: int
    origin: LabelOrigin
    created_at: datetime
    source_count: int = 0  # Not stored: counted when the label is read.


@dataclass(frozen=True, slots=True)
class LabelLink:
    """A label on a source."""

    source_id: UUID
    label_id: UUID
    origin: LabelOrigin


@dataclass(slots=True)
class LabelRun:
    """The state of the automatic labeling of one notebook."""

    notebook_id: UUID
    status: LabelRunStatus = LabelRunStatus.IDLE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    started_by: UUID | None = None  # who clicked: their budget and language

    def is_running(self, now: datetime) -> bool:
        """True while a run is going; one older than the limit counts as dead."""
        if self.status is not LabelRunStatus.RUNNING or self.started_at is None:
            return False
        return now - self.started_at < timedelta(minutes=STUCK_LABELING_MINUTES)

    def shown(self, now: datetime) -> "LabelRun":
        """What a client sees: a dead run is reported as `failed` (`timeout`)."""
        if self.status is LabelRunStatus.RUNNING and not self.is_running(now):
            return LabelRun(
                notebook_id=self.notebook_id,
                status=LabelRunStatus.FAILED,
                started_at=self.started_at,
                finished_at=self.finished_at,
                error=ERROR_TIMEOUT,
                started_by=self.started_by,
            )
        return self


def clean_label_name(value: str) -> str | None:
    """A one-line name of 1 to 40 characters, or None when it is empty or too long."""
    name = " ".join(value.split())
    if not name or len(name) > LABEL_NAME_MAX_CHARS:
        return None
    return name


def clean_label_emoji(value: str) -> str | None:
    """The emoji (at most 8 characters); an empty one becomes the default tag."""
    emoji = value.strip()
    if len(emoji) > LABEL_EMOJI_MAX_CHARS:
        return None
    return emoji or DEFAULT_LABEL_EMOJI
