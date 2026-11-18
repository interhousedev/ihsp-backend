"""In-memory fakes of the admission ports."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal, Self
from uuid import UUID

from app.modules.admission.domain.access import Assignment, Entitlement, StaffRole
from app.modules.admission.domain.catalog_proposals import CatalogProposal
from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogInstitution,
    CatalogScholarship,
    ListEntry,
)
from app.modules.admission.domain.courses import Course
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.intl_facts import fold_name
from app.modules.admission.domain.profile import AdmissionProfile
from app.modules.admission.domain.profile_words import ReviewRecord, WordsState
from app.modules.admission.domain.staff import (
    AuditRecord,
    CaseloadRow,
    Comment,
    SavedView,
    StaffUser,
)
from app.modules.admission.domain.supp_prompts import SuppPrompt
from app.modules.admission.ports.repositories import AuditEvent, OptIns
from app.shared.actor import Actor
from app.shared.contracts.academic import StudentRef
from app.shared.ids import new_id

NOW = dt.datetime(2026, 3, 2, 9, 0, tzinfo=dt.UTC)


class FakeStore:
    """State shared by every fake unit of work."""

    def __init__(self) -> None:
        """Start empty."""
        self.notifications: list[Any] = []
        self.checklist: list[Any] = []
        self.proposals: dict[UUID, CatalogProposal] = {}
        self.applied: list[CatalogProposal] = []
        self.known_targets: set[UUID] = set()
        self.institution_names: dict[str, UUID] = {}
        """Casefolded name, alias or domain of a known institution -> its id."""
        self.logos: dict[UUID, tuple[float | None, str | None]] = {}
        self.supp_prompts: dict[UUID, dict[str, list[SuppPrompt]]] = {}
        self.entitlements: dict[UUID, Entitlement] = {}
        self.assignments: dict[UUID, tuple[Assignment, ...]] = {}
        self.opt_ins: dict[UUID, OptIns] = {}
        self.audit: list[AuditEvent] = []
        self.courses: dict[UUID, Course] = {}
        self.runtime: dict[str, Any] = {}
        self.runtime_loads = 0
        self.institutions: dict[UUID, CatalogInstitution] = {}
        self.scholarships: list[CatalogScholarship] = []
        self.list_entries: dict[UUID, ListEntry] = {}
        self.checks: dict[UUID, AffordabilityCheck] = {}
        self.budget_bands: dict[UUID, str] = {}
        self.profiles: dict[UUID, AdmissionProfile] = {}
        self.words: dict[UUID, WordsState] = {}
        self.words_history: list[WordsState] = []
        self.reviews: list[ReviewRecord] = []
        self.roles: dict[UUID, StaffRole] = {}
        self.assignment_rows: dict[UUID, Assignment] = {}
        self.caseload_rows: list[CaseloadRow] = []
        self.views: dict[UUID, SavedView] = {}
        self.comments: dict[UUID, Comment] = {}
        self.export_tables: dict[str, list[dict[str, Any]]] = {}
        self.erased: list[UUID] = []
        self.stored_file_ids: list[UUID] = []
        self.audit_records: list[AuditRecord] = []


class _Access:
    def __init__(self, s: FakeStore, pending: list[AuditEvent]) -> None:
        self.s, self.pending = s, pending

    async def entitlement(self, user_id: UUID) -> Entitlement | None:
        return self.s.entitlements.get(user_id)

    async def assignments_for(self, user_id: UUID) -> tuple[Assignment, ...]:
        return self.s.assignments.get(user_id, ())

    async def opt_ins(self, user_ids: Sequence[UUID]) -> dict[UUID, OptIns]:
        return {u: self.s.opt_ins[u] for u in user_ids if u in self.s.opt_ins}

    async def set_opt_in(self, user_id: UUID, field: str, value: bool) -> None:
        cur = self.s.opt_ins.get(user_id, OptIns())
        self.s.opt_ins[user_id] = replace(cur, **{field: value})

    def audit(self, event: AuditEvent) -> None:
        self.pending.append(event)


class _Courses:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def list_for(self, student_id: UUID) -> list[Course]:
        return [c for c in self.s.courses.values() if c.student_id == student_id]

    async def get(self, course_id: UUID) -> Course | None:
        return self.s.courses.get(course_id)

    async def find(
        self, student_id: UUID, source: str, source_ref: str
    ) -> Course | None:
        return next(
            (
                c
                for c in self.s.courses.values()
                if (c.student_id, c.source, c.source_ref)
                == (student_id, source, source_ref)
            ),
            None,
        )

    async def add(self, course: Course) -> Course:
        row = replace(course, id=new_id(), created_at=NOW)
        assert row.id is not None
        self.s.courses[row.id] = row
        return row

    async def set_included(self, course_id: UUID, included: bool) -> Course:
        row = replace(self.s.courses[course_id], included=included)
        self.s.courses[course_id] = row
        return row


class _Profiles:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def get(self, student_id: UUID) -> AdmissionProfile | None:
        row = self.s.profiles.get(student_id)
        return replace(row, answers=dict(row.answers)) if row else None

    async def save(
        self, profile: AdmissionProfile, expected_lock: int | None
    ) -> AdmissionProfile:
        row = self.s.profiles.get(profile.student_id)
        if (row.lock_version if row else None) != expected_lock:
            raise AdmissionConflictError()
        profile.lock_version = 0 if expected_lock is None else expected_lock + 1
        self.s.profiles[profile.student_id] = replace(
            profile, answers=dict(profile.answers)
        )
        return profile

    async def get_words(self, student_id: UUID) -> WordsState | None:
        row = self.s.words.get(student_id)
        return replace(row) if row else None

    async def save_words(
        self, state: WordsState, expected_lock: int | None, *, history: bool
    ) -> WordsState:
        row = self.s.words.get(state.student_id)
        if (row.lock_version if row else None) != expected_lock:
            raise AdmissionConflictError()
        state.lock_version = 0 if expected_lock is None else expected_lock + 1
        self.s.words[state.student_id] = replace(state)
        if history:
            self.s.words_history.append(replace(state))
        return state


class _Reviews:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def find(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> ReviewRecord | None:
        return next(
            (
                r
                for r in self.s.reviews
                if (r.target_kind, r.target_id, r.input_hash)
                == (target_kind, target_id, input_hash)
            ),
            None,
        )

    async def latest(self, student_id: UUID, kind: str) -> ReviewRecord | None:
        rows = [
            r
            for r in self.s.reviews
            if r.student_id == student_id and r.target_kind == kind
        ]
        return rows[-1] if rows else None

    async def count_since(self, student_id: UUID, task: str, since: dt.datetime) -> int:
        return sum(
            1 for r in self.s.reviews if r.student_id == student_id and r.task == task
        )

    async def add(self, review: ReviewRecord) -> ReviewRecord:
        stored = replace(review, id=new_id(), created_at=NOW)
        self.s.reviews.append(stored)
        return stored


class FakeAi:
    """Scripted StructuredAi: returns `reply`, counts calls."""

    def __init__(self, reply: dict[str, Any]) -> None:
        """Keep the reply."""
        self.reply = reply
        self.calls = 0

    async def json(self, **_: Any) -> tuple[dict[str, Any], str]:
        self.calls += 1
        return self.reply, "fake-model"


class _Runtime:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def load(self) -> dict[str, Any]:
        self.s.runtime_loads += 1
        return dict(self.s.runtime)

    async def save(self, key: str, value: Any, user_id: Any) -> None:
        self.s.runtime[key] = value


class _Catalog:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def institutions(
        self, *, country: str | None = None
    ) -> list[CatalogInstitution]:
        rows = [i for i in self.s.institutions.values() if country in (None, i.country)]
        return sorted(rows, key=lambda i: i.name)

    async def institution(self, institution_id: UUID) -> CatalogInstitution | None:
        return self.s.institutions.get(institution_id)

    async def scholarships(
        self,
        *,
        institution_id: UUID | None = None,
        country: str | None = None,
        basis: str | None = None,
        coverage_min: int | None = None,
    ) -> list[CatalogScholarship]:
        return [
            x
            for x in self.s.scholarships
            if institution_id in (None, x.institution_id)
            and country in (None, x.country)
            and basis in (None, x.basis)
            and (coverage_min is None or (x.coverage_max or 0) >= coverage_min)
        ]


class _Shortlist:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def entries(self, student_id: UUID) -> list[ListEntry]:
        return [e for e in self.s.list_entries.values() if e.student_id == student_id]

    async def entry(self, entry_id: UUID) -> ListEntry | None:
        return self.s.list_entries.get(entry_id)

    async def find(self, student_id: UUID, institution_id: UUID) -> ListEntry | None:
        for e in self.s.list_entries.values():
            if e.student_id == student_id and e.institution_id == institution_id:
                return e
        return None

    async def add(self, entry: ListEntry) -> ListEntry:
        self.s.list_entries[entry.id] = entry
        return entry

    async def save(self, entry: ListEntry, *, expected_lock: int) -> ListEntry:
        from app.modules.admission.domain.errors import AdmissionConflictError

        cur = self.s.list_entries[entry.id]
        if cur.lock_version != expected_lock:
            raise AdmissionConflictError()
        new = replace(entry, lock_version=expected_lock + 1)
        self.s.list_entries[entry.id] = new
        return new

    async def delete(self, entry_id: UUID) -> None:
        self.s.list_entries.pop(entry_id, None)

    async def budget_band(self, student_id: UUID) -> str | None:
        return self.s.budget_bands.get(student_id)

    async def affordability(self, entry_id: UUID) -> AffordabilityCheck | None:
        return self.s.checks.get(entry_id)

    async def save_affordability(self, check: AffordabilityCheck) -> None:
        self.s.checks[check.list_entry_id] = check


class _Staff:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def role(self, role_id: UUID) -> StaffRole | None:
        return self.s.roles.get(role_id)

    async def roles(self) -> list[StaffRole]:
        return [r for r in self.s.roles.values() if r.archived_at is None]

    async def assignment(self, assignment_id: UUID) -> Assignment | None:
        return self.s.assignment_rows.get(assignment_id)

    async def live_assignments(self, kind: str, scope_kind: str) -> list[Assignment]:
        return [
            a
            for a in self.s.assignment_rows.values()
            if a.role.kind == kind
            and a.scope_kind == scope_kind
            and a.revoked_at is None
            and a.parent_assignment_id is None
        ]

    async def add_assignment(self, assignment: Assignment) -> Assignment:
        self.s.assignment_rows[assignment.id] = assignment
        return assignment

    async def revoke_assignment(
        self, assignment_id: UUID, now: dt.datetime, reason: str
    ) -> list[Assignment]:
        out: list[Assignment] = []
        for key, row in list(self.s.assignment_rows.items()):
            if key == assignment_id or row.parent_assignment_id == assignment_id:
                row = replace(row, revoked_at=now)
                self.s.assignment_rows[key] = row
                out.append(row)
        return out

    async def caseload(
        self, student_ids: Sequence[UUID] | None, now: dt.datetime
    ) -> list[CaseloadRow]:
        return [
            r
            for r in self.s.caseload_rows
            if student_ids is None or r.student_id in student_ids
        ]

    async def saved_views(self, user_id: UUID) -> list[SavedView]:
        return [v for v in self.s.views.values() if v.user_id == user_id]

    async def add_saved_view(self, view: SavedView) -> SavedView:
        self.s.views[view.id] = view
        return view

    async def update_saved_view(self, view: SavedView) -> SavedView:
        old = self.s.views[view.id]
        if old.lock_version != view.lock_version:
            raise AdmissionConflictError()
        view = replace(view, lock_version=old.lock_version + 1)
        self.s.views[view.id] = view
        return view

    async def delete_saved_view(self, view_id: UUID, user_id: UUID) -> bool:
        view = self.s.views.get(view_id)
        if view is None or view.user_id != user_id:
            return False
        del self.s.views[view_id]
        return True


class _Comments:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def add(self, comment: Comment) -> Comment:
        self.s.comments[comment.id] = comment
        return comment

    async def get(self, comment_id: UUID) -> Comment | None:
        return self.s.comments.get(comment_id)

    async def for_target(
        self, student_id: UUID, target_kind: str, target_id: UUID
    ) -> list[Comment]:
        return [
            c
            for c in self.s.comments.values()
            if (c.student_id, c.target_kind, c.target_id)
            == (student_id, target_kind, target_id)
        ]

    async def inbox(self, student_id: UUID, limit: int) -> list[Comment]:
        return [
            c
            for c in self.s.comments.values()
            if c.student_id == student_id
            and c.author_id != student_id
            and c.visibility == "student_and_staff"
        ][:limit]

    async def delete(self, comment_id: UUID, now: dt.datetime) -> None:
        self.s.comments.pop(comment_id, None)


class _Privacy:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def export(self, student_id: UUID) -> dict[str, list[dict[str, Any]]]:
        return self.s.export_tables

    async def erase(self, student_id: UUID) -> dict[str, int]:
        self.s.erased.append(student_id)
        return {t: len(r) for t, r in self.s.export_tables.items()}

    async def stored_file_ids(self, student_id: UUID) -> list[UUID]:
        return list(self.s.stored_file_ids)

    async def audit(self, student_id: UUID, limit: int) -> list[AuditRecord]:
        return self.s.audit_records[:limit]


class _CatalogProposals:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def add(self, proposal: CatalogProposal) -> CatalogProposal:
        self.s.proposals[proposal.id] = proposal
        return proposal

    async def get(self, proposal_id: UUID) -> CatalogProposal | None:
        return self.s.proposals.get(proposal_id)

    async def list(
        self, *, status: str | None = None, proposed_by: UUID | None = None
    ) -> list[CatalogProposal]:
        return [
            p
            for p in self.s.proposals.values()
            if (status is None or p.status == status)
            and (proposed_by is None or p.proposed_by == proposed_by)
        ]

    async def target_exists(self, kind: str, target_id: UUID) -> bool:
        return target_id in self.s.known_targets

    async def set_logo(
        self, institution_id: UUID, *, zoom: float | None, fit: str | None
    ) -> bool:
        if institution_id not in self.s.known_targets:
            return False
        self.s.logos[institution_id] = (zoom, fit)
        return True

    async def lock_submissions(self) -> None:
        return None

    async def find_duplicate(
        self, names: Sequence[str], website_domain: str | None
    ) -> tuple[Literal["institution", "proposal"], UUID] | None:
        known = {fold_name(k): v for k, v in self.s.institution_names.items()}
        for key in (*names, website_domain):
            if key is not None and key in known:
                return "institution", known[key]
        for p in self.s.proposals.values():
            if p.kind == "institution" and p.status == "pending" and not p.target_id:
                raw = [p.payload.get("name"), *(p.payload.get("aliases") or [])]
                if any(isinstance(n, str) and fold_name(n) in names for n in raw):
                    return "proposal", p.id
                pd = p.payload.get("website_domain")
                if (
                    website_domain
                    and isinstance(pd, str)
                    and fold_name(pd) == website_domain
                ):
                    return "proposal", p.id
        return None

    async def apply(
        self, proposal: CatalogProposal, *, reviewer_id: UUID, now: dt.datetime
    ) -> UUID:
        self.s.applied.append(proposal)
        return proposal.target_id or new_id()

    async def save_review(
        self, proposal: CatalogProposal, *, expected_lock: int
    ) -> CatalogProposal:
        if self.s.proposals[proposal.id].lock_version != expected_lock:
            raise AdmissionConflictError()
        saved = replace(proposal, lock_version=expected_lock + 1)
        self.s.proposals[proposal.id] = saved
        return saved


class FakeDirectory:
    """Staff directory over a dict."""

    def __init__(self, users: Sequence[StaffUser] = ()) -> None:
        """Index the users."""
        self.users = {u.user_id: u for u in users}

    async def staff_user(self, user_id: UUID) -> StaffUser | None:
        """Return the user or None."""
        return self.users.get(user_id)


class _Checklist:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    async def for_student(self, student_id: UUID) -> list[Any]:
        return [i for i in self.items if i.student_id == student_id]

    async def ensure(self, items: Sequence[Any]) -> None:
        have = {(i.student_id, i.list_entry_id, i.template_key) for i in self.items}
        self.items.extend(
            i
            for i in items
            if (i.student_id, i.list_entry_id, i.template_key) not in have
        )


class _SuppPrompts:
    def __init__(self, s: FakeStore) -> None:
        self.s = s

    async def institution_exists(self, institution_id: UUID) -> bool:
        return (
            institution_id in self.s.known_targets
            or institution_id in self.s.institutions
        )

    async def by_cycle(self, institution_id: UUID) -> dict[str, list[SuppPrompt]]:
        return dict(self.s.supp_prompts.get(institution_id, {}))

    async def replace(
        self, institution_id: UUID, cycle: str, prompts: Sequence[SuppPrompt]
    ) -> None:
        by = self.s.supp_prompts.setdefault(institution_id, {})
        if prompts:
            by[cycle] = list(prompts)
        else:
            by.pop(cycle, None)


class _NoDeadlines:
    async def current(self, **_: Any) -> list[Any]:
        return []


class FakeUow:
    """Unit of work over a FakeStore; audit events land only on commit."""

    def __init__(self, s: FakeStore) -> None:
        """Bind the store."""
        self._pending: list[AuditEvent] = []
        self.s = s
        self.access = _Access(s, self._pending)
        self.courses = _Courses(s)
        self.runtime_settings = _Runtime(s)
        self.catalog = _Catalog(s)
        self.catalog_proposals = _CatalogProposals(s)
        self.shortlist = _Shortlist(s)
        self.profiles = _Profiles(s)
        self.reviews = _Reviews(s)
        self.staff = _Staff(s)
        self.comments = _Comments(s)
        self.privacy = _Privacy(s)
        self.checklist: Any = _Checklist(s.checklist)
        self.deadlines: Any = _NoDeadlines()
        self.notify: Any = lambda *drafts: s.notifications.extend(drafts)
        self.supp_prompts = _SuppPrompts(s)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._pending.clear()

    async def commit(self) -> None:
        self.s.audit.extend(self._pending)
        self._pending.clear()


class FakeMembership:
    """Students and their groups."""

    def __init__(self, students: Sequence[StudentRef] = ()) -> None:
        """Keep the students."""
        self.by_id = {s.user_id: s for s in students}

    async def student(self, user_id: UUID) -> StudentRef | None:
        return self.by_id.get(user_id)

    async def group_ids_for(
        self, user_ids: Sequence[UUID]
    ) -> dict[UUID, frozenset[UUID]]:
        return {
            u: frozenset({self.by_id[u].group_id}) for u in user_ids if u in self.by_id
        }

    async def students_in_groups(self, group_ids: Sequence[UUID]) -> list[UUID]:
        return [s.user_id for s in self.by_id.values() if s.group_id in group_ids]


class FakeConsents:
    """Purpose consents per user."""

    def __init__(self, granted: dict[UUID, frozenset[str]] | None = None) -> None:
        """Keep the grants."""
        self.grants = granted or {}

    async def granted(self, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[str]]:
        return {u: self.grants[u] for u in user_ids if u in self.grants}


class FakeSources:
    """Live academic and LMS courses."""

    def __init__(self, academic: list[Course], lms: list[Course]) -> None:
        """Keep the courses."""
        self.academic, self.lms = academic, lms

    async def academic_courses(self, student_id: UUID) -> list[Course]:
        return [replace(c, student_id=student_id) for c in self.academic]

    async def lms_courses(self, actor: Actor) -> list[Course]:
        return list(self.lms)

    async def lms_catalog(self, actor: Actor, query: str | None) -> list[Course]:
        q = (query or "").lower()
        catalog = getattr(self, "catalog", [])
        return [c for c in catalog if q in c.title.lower()]

    async def lms_enroll(self, actor: Actor, course_id: UUID) -> None:
        self.enrolled = [*getattr(self, "enrolled", []), course_id]


def student_ref(user_id: UUID, group_id: UUID, group_name: str = "11-A") -> StudentRef:
    """Return an active student record."""
    return StudentRef(
        user_id=user_id,
        group_id=group_id,
        group_name=group_name,
        subgroup=None,
        status="active",
        synced_at=NOW,
    )
