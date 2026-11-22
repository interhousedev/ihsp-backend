"""Essays: drafts, version snapshots, the plan, links and the ideas board."""

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import CharLimitError, ItemLimitError
from app.modules.admission.domain.essay_flow import MAX_GROUP, PromptTarget

EssayKind = Literal["personal_statement", "supplemental", "other"]
EssayStatus = Literal["draft", "final"]
VersionSource = Literal["interval", "explicit", "restore"]
IdeaStatus = Literal["explore", "keep", "drop"]
LinkKind = Literal["item", "profile_answer"]

KINDS: Final = ("personal_statement", "supplemental", "other")
VERSION_SOURCES: Final = ("interval", "explicit", "restore")
IDEA_STATUSES: Final = ("explore", "keep", "drop")
LINK_KINDS: Final = ("item", "profile_answer")

MAX_ESSAYS: Final = 40
TITLE_MAX: Final = 120
PROMPT_MAX: Final = 2000
BODY_MAX: Final = 30000
NOTES_MAX: Final = 4000
WORD_LIMIT_MAX: Final = 5000
MAX_SECTIONS: Final = 12
HEADING_MAX: Final = 120
SECTION_NOTE_MAX: Final = 1000
MAX_LINKS: Final = 20
VERSION_NAME_MAX: Final = 60
MAX_IDEAS: Final = 100
IDEA_MAX: Final = 1000
MAX_TAGS: Final = 8
TAG_MAX: Final = 32
SNAPSHOT_INTERVAL: Final = dt.timedelta(minutes=10)

_WORD = re.compile(r"\S+")


def word_count(text: str) -> int:
    """Count whitespace-separated words, the way the editor counts them."""
    return len(_WORD.findall(text))


def _limit(name: str, value: str, limit: int, *, required: bool = False) -> None:
    count = len(value)
    if count > limit or (required and not value.strip()):
        raise CharLimitError(params={"field": name, "limit": limit, "count": count})


@dataclass(frozen=True, slots=True)
class PlanSection:
    """One outline section of the essay plan."""

    heading: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class EssayLink:
    """A link to an activity/honor (`item`) or a profile answer (question id)."""

    kind: LinkKind
    ref: str


@dataclass(slots=True)
class Essay:
    """An essay with its live draft; `current_version` is the last snapshot."""

    id: UUID
    student_id: UUID
    kind: EssayKind = "personal_statement"
    title: str = ""
    prompt_text: str = ""
    word_limit: int | None = None
    list_entry_id: UUID | None = None
    body: str = ""
    notes: str = ""
    plan: tuple[PlanSection, ...] = ()
    links: tuple[EssayLink, ...] = ()
    targets: tuple[PromptTarget, ...] = ()
    forked_from: UUID | None = None
    status: EssayStatus = "draft"
    current_version: int = 0
    last_snapshot_at: dt.datetime | None = None
    lock_version: int = 0
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    unreadable: bool = False
    """The sealed text is lost (key gone or changed); only the plain fields are set."""

    @property
    def word_count(self) -> int:
        """Words in the live draft."""
        return word_count(self.body)

    def validate(self) -> None:
        """Reject over-long fields and malformed plans or links."""
        _limit("title", self.title, TITLE_MAX)
        _limit("prompt_text", self.prompt_text, PROMPT_MAX)
        _limit("body", self.body, BODY_MAX)
        _limit("notes", self.notes, NOTES_MAX)
        if self.word_limit is not None and not 1 <= self.word_limit <= WORD_LIMIT_MAX:
            raise CharLimitError(
                params={
                    "field": "word_limit",
                    "limit": WORD_LIMIT_MAX,
                    "count": self.word_limit,
                }
            )
        if len(self.plan) > MAX_SECTIONS:
            raise ItemLimitError(params={"kind": "plan", "limit": MAX_SECTIONS})
        for section in self.plan:
            _limit("heading", section.heading, HEADING_MAX, required=True)
            _limit("note", section.note, SECTION_NOTE_MAX)
        if len(self.links) > MAX_LINKS:
            raise ItemLimitError(params={"kind": "links", "limit": MAX_LINKS})
        if len(self.targets) > MAX_GROUP:
            raise ItemLimitError(params={"kind": "targets", "limit": MAX_GROUP})


@dataclass(frozen=True, slots=True)
class EssayVersion:
    """A snapshot of the draft; only `shared` versions reach staff."""

    id: UUID
    essay_id: UUID
    version: int
    body: str
    created_by: UUID
    source: VersionSource = "explicit"
    name: str | None = None
    shared: bool = False
    word_count: int = 0
    created_at: dt.datetime | None = None


@dataclass(slots=True)
class EssayIdea:
    """A brainstorm card, optionally tied to one essay."""

    id: UUID
    student_id: UUID
    body: str
    essay_id: UUID | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    status: IdeaStatus = "explore"
    sort_order: int = 0
    lock_version: int = 0
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    def validate(self) -> None:
        """Reject an empty or long body and too many or too long tags."""
        _limit("body", self.body, IDEA_MAX, required=True)
        if len(self.tags) > MAX_TAGS:
            raise ItemLimitError(params={"kind": "tags", "limit": MAX_TAGS})
        for tag in self.tags:
            _limit("tag", tag, TAG_MAX, required=True)
