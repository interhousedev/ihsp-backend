"""The JSON-shaped views of assessments (AssessmentItem and its staff variant)."""

import datetime as dt
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    AssessmentReader,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.periods import (
    TermControls,
    UndatedControl,
    period_of,
)
from app.modules.academic.domain.assessments.records import Assessment
from app.modules.academic.domain.assessments.rules import days_left
from app.modules.academic.domain.marks.names import localized
from app.modules.academic.domain.marks.read_models import SubjectInfo
from app.shared.contracts.identity import IdentityDirectory, UserRef


@dataclass(frozen=True, slots=True)
class AssessmentView:
    """Subjects, groups, people and terms resolved once for a whole response."""

    locale: str
    today: dt.date
    subjects: Mapping[UUID, SubjectInfo]
    group_names: Mapping[UUID, str] = field(default_factory=dict)
    users: Mapping[UUID, UserRef] = field(default_factory=dict)
    terms: Sequence[TermControls] = ()

    def subject_ref(self, subject_id: UUID) -> dict[str, Any]:
        """Return `SubjectRef` in the caller's locale."""
        info = self.subjects.get(subject_id)
        if info is None:
            return {"id": subject_id, "name": "", "short_name": ""}
        name = localized(info.name, self.locale)
        return {"id": subject_id, "name": name, "short_name": info.short_name or name}

    def item(self, a: Assessment) -> dict[str, Any]:
        """Return `AssessmentItem` of a stored control."""
        period = period_of(a.control, a.date, self.terms)
        return {
            "id": a.id,
            "subject": self.subject_ref(a.subject_id),
            "kind": a.kind,
            "title": a.title,
            "date": a.date,
            "starts_at": a.starts_at,
            "lesson_id": a.lesson_id,
            "room": a.room,
            "status": a.status,
            "source": a.source,
            "note": a.note,
            "days_left": days_left(a.date, self.today),
            "control": a.control,
            "period": (
                None if period is None else {"start": period.start, "end": period.end}
            ),
            "has_date": True,
        }

    def undated_item(self, c: UndatedControl) -> dict[str, Any]:
        """Return `AssessmentItem` of a control week that has no subject date yet."""
        day = c.date(self.today)
        return {
            "id": c.id,
            "subject": self.subject_ref(c.subject_id),
            "kind": c.kind,
            "title": "",
            "date": day,
            "starts_at": None,
            "lesson_id": None,
            "room": None,
            "status": "planned",
            "source": "admin",
            "note": None,
            "days_left": days_left(day, self.today),
            "control": c.control,
            "period": {"start": c.period.start, "end": c.period.end},
            "has_date": False,
        }

    def staff_item(self, a: Assessment) -> dict[str, Any]:
        """Return `StaffAssessmentItem`: the item with audience and author."""
        return {
            **self.item(a),
            "audience": self._audience(a.audience),
            "created_by": self._person(a.created_by),
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }

    def staff_undated_item(self, c: UndatedControl) -> dict[str, Any]:
        """Return `StaffAssessmentItem` of a control week without a subject date."""
        return {
            **self.undated_item(c),
            "audience": self._audience(c.audience),
            "created_by": None,
            "created_at": None,
            "updated_at": None,
        }

    def _audience(self, keys: Sequence[str]) -> list[dict[str, Any]]:
        items = []
        for key in keys:
            group_id, subgroup = audience_keys.parse(key)
            items.append(
                {
                    "group_id": group_id,
                    "group_name": self.group_names.get(group_id, ""),
                    "subgroup": subgroup,
                }
            )
        return items

    def _person(self, user_id: UUID | None) -> dict[str, Any] | None:
        user = None if user_id is None else self.users.get(user_id)
        if user is None:
            return None
        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }


async def build_view(
    reader: AssessmentReader,
    identity: IdentityDirectory,
    rows: Collection[Assessment],
    *,
    locale: str,
    today: dt.date,
    staff: bool,
    extra_subjects: Collection[UUID] = (),
    extra_groups: Collection[UUID] = (),
) -> AssessmentView:
    """Load what the response needs; people and group names only for staff views."""
    subject_ids = {a.subject_id for a in rows} | set(extra_subjects)
    subjects = await reader.subjects(subject_ids) if subject_ids else {}
    terms = await reader.terms()
    if not staff:
        return AssessmentView(locale, today, subjects, terms=terms)
    groups = audience_keys.group_ids(k for a in rows for k in a.audience)
    groups |= set(extra_groups)
    authors = sorted({a.created_by for a in rows if a.created_by}, key=str)
    return AssessmentView(
        locale=locale,
        today=today,
        subjects=subjects,
        group_names=await reader.group_names(groups) if groups else {},
        users=await identity.get_users(authors) if authors else {},
        terms=terms,
    )


async def caller_locale(identity: IdentityDirectory, user_id: UUID) -> str:
    """Return the caller's locale (ru when the user is unknown)."""
    user = await identity.get_user(user_id)
    return "ru" if user is None else user.locale
