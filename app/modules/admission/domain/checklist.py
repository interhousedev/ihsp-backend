"""Checklist templates and generation (§12.1).

A template has a stable `template_key` (identity of the row for idempotency) and a
`title_key` (the web label `documents.checklist.<title_key>`). Shared templates
produce one row per student; entry templates one row per list entry and are
filtered by the entry's round.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.domain.chooser import ListEntry
from app.modules.admission.domain.documents import (
    ChecklistItem,
    ChecklistStatus,
    Deadline,
)
from app.modules.admission.domain.errors import InvalidProofUrlError
from app.modules.admission.domain.urls import is_https_url
from app.shared.ids import new_id

RULE_VERSION = 1
BINDING_ROUNDS = frozenset({"ED", "ED2"})
ALL_ROUNDS = frozenset({"RD", "EA", "ED", "ED2", "REA", "SCEA", "rolling", "other"})


@dataclass(frozen=True, slots=True)
class ChecklistTemplate:
    """One generated checklist line."""

    template_key: str
    title_key: str
    owner: str
    doc_kind: str | None = None
    rounds: frozenset[str] = ALL_ROUNDS
    timed: bool = False


SHARED_TEMPLATES: tuple[ChecklistTemplate, ...] = (
    ChecklistTemplate("shared.transcript", "transcript", "officer", "transcript"),
    ChecklistTemplate("shared.passport", "passport", "student", "passport"),
    ChecklistTemplate("shared.translation", "translation", "student", "translation"),
)

ENTRY_TEMPLATES: tuple[ChecklistTemplate, ...] = (
    ChecklistTemplate(
        "entry.application_form", "application_form", "student", None, timed=True
    ),
    ChecklistTemplate("entry.essay", "essay", "student", None, timed=True),
    ChecklistTemplate(
        "entry.recommendation", "recommendation", "teacher", "rec", timed=True
    ),
    ChecklistTemplate(
        "entry.school_report", "school_report", "counselor", "school_report"
    ),
    ChecklistTemplate("entry.test_report", "test_report", "student", "test_report"),
    ChecklistTemplate("entry.aid_forms", "aid_forms", "student", "bank"),
    ChecklistTemplate("entry.fee", "fee", "student"),
    ChecklistTemplate(
        "entry.binding_agreement", "binding_agreement", "student", None, BINDING_ROUNDS
    ),
)


def shared_items(
    student_id: UUID, existing: Iterable[ChecklistItem]
) -> list[ChecklistItem]:
    """New shared rows the student does not have yet."""
    have = {i.template_key for i in existing if i.list_entry_id is None}
    return [
        ChecklistItem(
            id=new_id(),
            student_id=student_id,
            template_key=t.template_key,
            title_key=t.title_key,
            owner=t.owner,
            rule_version=RULE_VERSION,
        )
        for t in SHARED_TEMPLATES
        if t.template_key not in have
    ]


def _deadline_for(entry: ListEntry, deadlines: Sequence[Deadline]) -> Deadline | None:
    live = [
        d
        for d in deadlines
        if d.institution_id == entry.institution_id and d.round == entry.round
    ]
    return max(live, key=lambda d: d.version, default=None)


def entry_items(
    entry: ListEntry,
    existing: Iterable[ChecklistItem],
    deadlines: Sequence[Deadline] = (),
) -> list[ChecklistItem]:
    """New rows of one list entry for its round; due dates only from known instants."""
    have = {i.template_key for i in existing if i.list_entry_id == entry.id}
    deadline = _deadline_for(entry, deadlines)
    out: list[ChecklistItem] = []
    for t in ENTRY_TEMPLATES:
        if entry.round not in t.rounds or t.template_key in have:
            continue
        status: ChecklistStatus = "todo"
        due = None
        if t.timed and deadline is not None:
            due = deadline.instant_utc
            if deadline.status == "confirm_with_uni":
                status = "confirm_with_uni"
        out.append(
            ChecklistItem(
                id=new_id(),
                student_id=entry.student_id,
                template_key=t.template_key,
                title_key=t.title_key,
                list_entry_id=entry.id,
                owner=t.owner,
                status=status,
                due_utc=due,
                rule_version=RULE_VERSION,
            )
        )
    return out


URGENT_WITHIN = dt.timedelta(days=7)

# Where each template is done in the app; None = no page (the upload form
# on /documents/ itself, or a step outside the app).
DEEP_LINKS: dict[str, str] = {
    "shared.transcript": "/documents/#transcripts",
    "shared.translation": "/documents/",
    "entry.application_form": "/plan/",
    "entry.essay": "/essays/",
    "entry.recommendation": "/documents/",
    "entry.test_report": "/tests/",
}


def deep_link(template_key: str) -> str | None:
    """The in-app page where the item is done."""
    return DEEP_LINKS.get(template_key)


def is_urgent(
    item: ChecklistItem, now: dt.datetime, *, within: dt.timedelta = URGENT_WITHIN
) -> bool:
    """Urgent by the override, else by a deadline within `within` (or overdue).

    Finished items (done / n_a) are never urgent.
    """
    if item.status in ("done", "n_a"):
        return False
    if item.urgent_override is not None:
        return item.urgent_override
    return item.due_utc is not None and item.due_utc - now <= within


def quadrant(item: ChecklistItem, now: dt.datetime) -> str:
    """Eisenhower quadrant: do / schedule / delegate / drop."""
    urgent = is_urgent(item, now)
    if item.important:
        return "do" if urgent else "schedule"
    return "delegate" if urgent else "drop"


class Unset:
    """Marks a patch field that was not sent (distinct from an explicit null)."""


UNSET = Unset()


def clean_source_url(url: str | None) -> str | None:
    """A staff-set external link: http(s) only, trimmed; empty clears it."""
    value = (url or "").strip()
    if not value:
        return None
    if not is_https_url(value):
        raise InvalidProofUrlError()
    return value
