"""Reading lists (doc 3.11): audience, entries, limits and the read status."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
    ShelfState,
)
from app.modules.library.domain.errors import ListTooLongError
from app.modules.library.domain.taxonomy_errors import (
    ListEntryInvalidError,
    ListInvalidError,
)

TITLE_MAX = 200
DESCRIPTION_MAX = 2000
ENTRY_TITLE_MAX = 255
URL_MAX = 2000
NOTE_MAX = 500
WEEK_LABEL_MAX = 40
GROUPS_MAX = 30
YEAR_OF_STUDY_MAX = 4
_ACADEMIC_YEAR = re.compile(r"^\d{4}-\d{4}$")


@dataclass(slots=True)
class ReadingList:
    """A reading list of a teacher or a librarian; its entries are stored apart."""

    id: UUID
    owner_id: UUID
    title: str
    scope: ListScope
    status: ListStatus
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    subject_id: UUID | None = None
    group_ids: list[UUID] = field(default_factory=list)
    year_of_study: int | None = None
    academic_year: str | None = None
    term_half: int | None = None


@dataclass(frozen=True, slots=True)
class ReadingListEntry:
    """A library item or a plain link on a list, with the teacher's guidance."""

    position: int
    importance: Importance
    item_id: UUID | None = None
    url: str | None = None
    title: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    week_label: str | None = None
    due_on: date | None = None
    topic_id: UUID | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class EntryDraft:
    """An entry as the teacher sent it, before the checks."""

    importance: Importance
    item_id: UUID | None = None
    url: str | None = None
    title: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    week_label: str | None = None
    due_on: date | None = None
    topic_id: UUID | None = None
    note: str | None = None


# - - - The list itself - - -


def clean_list_text(title: str, description: str | None) -> tuple[str, str | None]:
    """The trimmed title (required) and description (None when blank)."""
    clean_title = " ".join(title.split())
    if not clean_title or len(clean_title) > TITLE_MAX:
        raise ListInvalidError(params={"field": "title"})
    clean_description = (description or "").strip()
    if len(clean_description) > DESCRIPTION_MAX:
        raise ListInvalidError(params={"field": "description"})
    return clean_title, clean_description or None


def validate_audience(
    scope: ListScope, subject_id: UUID | None, group_ids: Sequence[UUID]
) -> list[UUID]:
    """The groups, each once, after checking that scope, subject and groups agree."""
    groups = list(dict.fromkeys(group_ids))
    if scope is ListScope.SUBJECT and subject_id is None:
        raise ListInvalidError(params={"field": "subject_id"})
    if scope is ListScope.GROUPS and not groups:
        raise ListInvalidError(params={"field": "group_ids"})
    if scope is not ListScope.GROUPS and groups:
        raise ListInvalidError(params={"field": "group_ids"})
    if len(groups) > GROUPS_MAX:
        raise ListInvalidError(params={"field": "group_ids", "max": GROUPS_MAX})
    return groups


def validate_term(
    year_of_study: int | None, academic_year: str | None, term_half: int | None
) -> None:
    """Year of study 1 to 4, academic year like `2026-2027`, half 1 or 2."""
    if year_of_study is not None and not 1 <= year_of_study <= YEAR_OF_STUDY_MAX:
        raise ListInvalidError(params={"field": "year_of_study"})
    if academic_year is not None and not _ACADEMIC_YEAR.match(academic_year):
        raise ListInvalidError(params={"field": "academic_year"})
    if term_half is not None and term_half not in (1, 2):
        raise ListInvalidError(params={"field": "term_half"})


# - - - Entries - - -


def build_entries(
    drafts: Sequence[EntryDraft], max_items: int
) -> list[ReadingListEntry]:
    """Checked entries numbered in the order given; at most `max_items` of them."""
    if len(drafts) > max_items:
        raise ListTooLongError(params={"max": max_items})
    return [_entry(position, draft) for position, draft in enumerate(drafts)]


def _invalid(position: int, reason: str) -> ListEntryInvalidError:
    return ListEntryInvalidError(params={"position": position, "reason": reason})


def _entry(position: int, draft: EntryDraft) -> ReadingListEntry:
    if (draft.item_id is None) == (draft.url is None):
        raise _invalid(position, "item_or_url")
    if draft.page_from is not None and draft.page_from < 1:
        raise _invalid(position, "pages")
    if draft.page_to is not None and (
        draft.page_from is None or draft.page_to < draft.page_from
    ):
        raise _invalid(position, "pages")
    url, title = _target(position, draft)
    return ReadingListEntry(
        position=position,
        importance=draft.importance,
        item_id=draft.item_id,
        url=url,
        title=title,
        page_from=draft.page_from,
        page_to=draft.page_to,
        week_label=_short(position, draft.week_label, WEEK_LABEL_MAX, "week_label"),
        due_on=draft.due_on,
        topic_id=draft.topic_id,
        note=_short(position, draft.note, NOTE_MAX, "note"),
    )


def _target(position: int, draft: EntryDraft) -> tuple[str | None, str | None]:
    """The checked address and title: links keep both, items keep neither."""
    if draft.url is None:
        return None, None
    url = draft.url.strip()
    parts = urlsplit(url)
    if (
        len(url) > URL_MAX
        or parts.scheme not in ("http", "https")
        or not parts.netloc
        or " " in url
    ):
        raise _invalid(position, "url")
    title = " ".join((draft.title or "").split()) or url
    return url, title[:ENTRY_TITLE_MAX]


def _short(position: int, value: str | None, limit: int, reason: str) -> str | None:
    clean = (value or "").strip()
    if len(clean) > limit:
        raise _invalid(position, reason)
    return clean or None


# - - - Read status - - -


def read_state(
    entry: ReadingListEntry, states: Mapping[UUID, ShelfState]
) -> ShelfState | None:
    """The viewer's shelf state of the item of the entry (None for links)."""
    return states.get(entry.item_id) if entry.item_id is not None else None


def essential_progress(
    entries: Sequence[ReadingListEntry], states: Mapping[UUID, ShelfState]
) -> tuple[int, int]:
    """`(essential entries, essential entries the viewer finished)`."""
    essential = [e for e in entries if e.importance is Importance.ESSENTIAL]
    done = sum(1 for e in essential if read_state(e, states) is ShelfState.DONE)
    return len(essential), done
