"""Opportunities: moderation, recurrence projection, plans, planner, permissions."""

import dataclasses
import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.application.opportunities import (
    STUDENT_SUBMIT_LIMIT,
    CatalogFilter,
    OpportunityService,
)
from app.modules.admission.application.opportunity_planner import (
    AiPlan,
    OpportunityPlanner,
    clean_plan,
    place_rest,
)
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ConsentRequiredError,
    InvalidProofUrlError,
    InvalidTransitionError,
)
from app.modules.admission.domain.opportunities import (
    ItemOpportunityLink,
    Opportunity,
    OpportunityDraft,
    OpportunitySubmission,
    PlanEntry,
    TaxonomyNode,
    expected_this_cycle,
    occurrences,
    parse_rule,
    review_transition,
    upcoming_dates,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.personal_entries import (
    PersonalEntry,
    PlanDuplicateError,
)
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World
from tests.fakes.clock import FixedClock

import pytest


class FakeOpportunities:
    """In-memory OpportunityRepository."""

    def __init__(self) -> None:
        self.nodes: dict[UUID, TaxonomyNode] = {}
        self.rows: dict[UUID, Opportunity] = {}
        self.subs: dict[UUID, OpportunitySubmission] = {}
        self.plans: dict[tuple[UUID, UUID], PlanEntry] = {}
        self.ai: dict[UUID, tuple[dict[str, Any], dt.datetime]] = {}
        self.links: dict[UUID, ItemOpportunityLink] = {}
        self.personal: dict[UUID, PersonalEntry] = {}

    async def taxonomy(self) -> list[TaxonomyNode]:
        return list(self.nodes.values())

    async def get_node(self, node_id: UUID) -> TaxonomyNode | None:
        return self.nodes.get(node_id)

    async def save_node(self, node: TaxonomyNode) -> TaxonomyNode:
        self.nodes[node.id] = node
        return node

    async def delete_node(self, node_id: UUID) -> None:
        self.nodes.pop(node_id, None)

    async def node_in_use(self, node_ids: list[UUID]) -> bool:
        return any(set(node_ids) & set(o.draft.subject_ids) for o in self.rows.values())

    async def list_published(self) -> list[Opportunity]:
        return [o for o in self.rows.values() if not o.archived]

    async def get(self, opportunity_id: UUID) -> Opportunity | None:
        return self.rows.get(opportunity_id)

    async def get_many(self, opportunity_ids: list[UUID]) -> list[Opportunity]:
        return [self.rows[i] for i in opportunity_ids if i in self.rows]

    async def apply(
        self, draft: OpportunityDraft, *, target_id: UUID | None, by: UUID
    ) -> UUID:
        oid = target_id or new_id()
        old = self.rows.get(oid)
        self.rows[oid] = Opportunity(
            id=oid,
            draft=draft,
            created_by=old.created_by if old else by,
            created_at=old.created_at if old else NOW,
            updated_at=NOW,
            archived=False,
            lock_version=(old.lock_version + 1) if old else 1,
        )
        return oid

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        o = self.rows[opportunity_id]
        self.rows[opportunity_id] = dataclasses.replace(o, archived=archived)

    async def add_submission(
        self, submission: OpportunitySubmission
    ) -> OpportunitySubmission:
        self.subs[submission.id] = submission
        return submission

    async def get_submission(self, submission_id: UUID) -> OpportunitySubmission | None:
        return self.subs.get(submission_id)

    async def list_submissions(
        self, *, status: str | None, submitted_by: UUID | None
    ) -> list[OpportunitySubmission]:
        return [
            s
            for s in self.subs.values()
            if (status is None or s.status == status)
            and (submitted_by is None or s.submitted_by == submitted_by)
        ]

    async def save_review(
        self, submission: OpportunitySubmission, *, expected_lock: int
    ) -> OpportunitySubmission:
        cur = self.subs[submission.id]
        if cur.lock_version != expected_lock or cur.status != "pending":
            raise AdmissionConflictError()
        saved = dataclasses.replace(submission, lock_version=cur.lock_version + 1)
        self.subs[saved.id] = saved
        return saved

    async def item_link(self, item_id: UUID) -> ItemOpportunityLink | None:
        return self.links.get(item_id)

    async def save_item_link(self, link: ItemOpportunityLink) -> None:
        self.links[link.item_id] = link

    async def delete_item_link(self, item_id: UUID) -> bool:
        return self.links.pop(item_id, None) is not None

    async def resolve_item_links(
        self, submission_id: UUID, opportunity_id: UUID
    ) -> int:
        hits = [k for k, v in self.links.items() if v.submission_id == submission_id]
        for key in hits:
            self.links[key] = dataclasses.replace(
                self.links[key], opportunity_id=opportunity_id
            )
        return len(hits)

    async def plan(self, student_id: UUID) -> list[PlanEntry]:
        return [e for (s, _), e in self.plans.items() if s == student_id]

    async def save_plan_entry(self, entry: PlanEntry) -> PlanEntry:
        self.plans[(entry.student_id, entry.opportunity_id)] = entry
        return entry

    async def delete_plan_entry(self, student_id: UUID, opportunity_id: UUID) -> bool:
        return self.plans.pop((student_id, opportunity_id), None) is not None

    async def ai_plan(
        self, student_id: UUID
    ) -> tuple[dict[str, Any], dt.datetime] | None:
        return self.ai.get(student_id)

    async def save_ai_plan(
        self, student_id: UUID, plan: dict[str, Any], at: dt.datetime
    ) -> None:
        self.ai[student_id] = (plan, at)

    async def personal_entries(self, student_id: UUID) -> list[PersonalEntry]:
        return sorted(
            (p for p in self.personal.values() if p.student_id == student_id),
            key=lambda p: p.created_at,
        )

    async def get_personal(
        self, student_id: UUID, entry_id: UUID
    ) -> PersonalEntry | None:
        found = self.personal.get(entry_id)
        return found if found is not None and found.student_id == student_id else None

    async def personal_by_key(
        self, student_id: UUID, dedup_key: str
    ) -> PersonalEntry | None:
        return next(
            (
                p
                for p in self.personal.values()
                if p.student_id == student_id and p.dedup_key == dedup_key
            ),
            None,
        )

    async def personal_by_submission(self, submission_id: UUID) -> list[PersonalEntry]:
        return [p for p in self.personal.values() if p.submission_id == submission_id]

    async def add_personal(self, entry: PersonalEntry) -> PersonalEntry:
        if await self.personal_by_key(entry.student_id, entry.dedup_key):
            raise PlanDuplicateError()
        self.personal[entry.id] = entry
        return entry

    async def save_personal(
        self, entry: PersonalEntry, *, expected_lock: int
    ) -> PersonalEntry:
        current = self.personal.get(entry.id)
        if current is None or current.lock_version != expected_lock:
            raise AdmissionConflictError()
        twin = await self.personal_by_key(entry.student_id, entry.dedup_key)
        if twin is not None and twin.id != entry.id:
            raise PlanDuplicateError()
        saved = dataclasses.replace(entry, lock_version=expected_lock + 1)
        self.personal[entry.id] = saved
        return saved

    async def delete_personal(self, student_id: UUID, entry_id: UUID) -> bool:
        if await self.get_personal(student_id, entry_id) is None:
            return False
        del self.personal[entry_id]
        return True


class Env:
    def __init__(self) -> None:
        self.w = World()
        self.repo = FakeOpportunities()

        def uow() -> FakeUow:
            u = FakeUow(self.w.store)
            u.opportunities = self.repo  # type: ignore[attr-defined]
            return u

        self.uow = uow
        self.svc = OpportunityService(
            uow, self.w.policy, FixedClock(NOW)  # type: ignore[arg-type]
        )

    async def admin(self) -> Any:
        return await self.w.ctx(STAFF, Role.ADMIN)

    async def student(self) -> Any:
        return await self.w.ctx(STUDENT, Role.STUDENT)

    async def seed_subject(self) -> UUID:
        a = await self.admin()
        f = await self.svc.save_node(
            a,
            node_id=None,
            level="field",
            parent_id=None,
            names={"en": "STEM"},
            position=0,
        )
        sf = await self.svc.save_node(
            a,
            node_id=None,
            level="subfield",
            parent_id=f.id,
            names={"en": "Math"},
            position=0,
        )
        s = await self.svc.save_node(
            a,
            node_id=None,
            level="subject",
            parent_id=sf.id,
            names={"en": "Algebra"},
            position=0,
        )
        return s.id


def _draft(subject: UUID, **kw: Any) -> OpportunityDraft:
    base: dict[str, Any] = {
        "kind": "exam",
        "title": "SAT",
        "summary": None,
        "url": "https://example.org/sat",
        "provider": None,
        "subject_ids": (subject,),
        "grades": (10, 11),
        "registration_deadlines": (),
        "exam_dates": (),
        "last_year_dates": (dt.date(NOW.year - 1, 10, 5),),
        "recurrence": None,
        "lms_course_id": None,
        "materials": (),
        "note": None,
    }
    base.update(kw)
    return OpportunityDraft(**base)


# - - - State machine - - -


def test_review_transition() -> None:
    assert review_transition("pending", True, None) == "approved"
    assert review_transition("pending", False, "dup") == "rejected"
    with pytest.raises(LookupError):
        review_transition("pending", False, " ")
    for done in ("approved", "rejected"):
        with pytest.raises(ValueError):
            review_transition(done, True, None)


async def test_submit_approve_publishes_and_audits() -> None:
    e = Env()
    subj = await e.seed_subject()
    sub = await e.svc.submit(await e.student(), _draft(subj))
    assert sub.status == "pending" and sub.submitter_role == "student"
    assert await e.svc.browse(CatalogFilter()) == []
    done = await e.svc.review(
        await e.admin(),
        sub.id,
        approve=True,
        reason=None,
        lock_version=sub.lock_version,
    )
    assert done.status == "approved" and done.applied_id is not None
    [o] = await e.svc.browse(CatalogFilter(subject_id=subj, grade=10))
    assert o.id == done.applied_id
    assert await e.svc.browse(CatalogFilter(grade=12)) == []
    actions = [a.action for a in e.w.store.audit]
    assert "opportunity.submitted" in actions
    assert "opportunity.submission_approved" in actions
    with pytest.raises(InvalidTransitionError):
        await e.svc.review(
            await e.admin(),
            sub.id,
            approve=False,
            reason="x",
            lock_version=done.lock_version,
        )


async def test_reject_needs_reason_and_edit_is_moderated() -> None:
    e = Env()
    subj = await e.seed_subject()
    a = await e.admin()
    first = await e.svc.submit(a, _draft(subj))
    pub = await e.svc.review(a, first.id, approve=True, reason=None, lock_version=0)
    edit = await e.svc.submit(
        await e.student(), _draft(subj, title="SAT 2"), target_id=pub.applied_id
    )
    with pytest.raises(ValidationFailedError):
        await e.svc.review(a, edit.id, approve=False, reason="", lock_version=0)
    with pytest.raises(AdmissionConflictError):
        await e.svc.review(a, edit.id, approve=False, reason="no", lock_version=9)
    rej = await e.svc.review(a, edit.id, approve=False, reason="no", lock_version=0)
    assert rej.status == "rejected" and rej.reason == "no"
    assert pub.applied_id is not None
    assert (await e.svc.get(pub.applied_id)).draft.title == "SAT"


async def test_submit_rejects_unknown_subject_and_http() -> None:
    e = Env()
    subj = await e.seed_subject()
    with pytest.raises(ValidationFailedError):
        await e.svc.submit(await e.student(), _draft(new_id()))
    with pytest.raises(InvalidProofUrlError):
        await e.svc.submit(await e.student(), _draft(subj, url="http://x.org"))


# - - - Permissions - - -


async def test_only_admins_moderate_and_edit_taxonomy() -> None:
    e = Env()
    subj = await e.seed_subject()
    st = await e.student()
    assert not e.svc.can_moderate(st) and e.svc.can_moderate(await e.admin())
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.save_node(
            st,
            node_id=None,
            level="field",
            parent_id=None,
            names={"en": "X"},
            position=0,
        )
    sub = await e.svc.submit(st, _draft(subj))
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.review(st, sub.id, approve=True, reason=None, lock_version=0)
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.set_archived(st, new_id(), True)
    other = await e.w.ctx(new_id(), Role.STUDENT)
    assert e.svc.may_submit(st)
    mine = await e.svc.submissions(st, status=None)
    assert [s.id for s in mine] == [sub.id]
    if e.svc.may_submit(other):
        assert await e.svc.submissions(other, status=None) == []


class CountingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.keys.append(key)
        if self.keys.count(key) > limit:
            raise RateLimitedError(params={"retry_after": window_seconds})


async def _helper_ctx(e: Env, *, grant: bool, kind: str = "counselor") -> Any:
    helper = new_id()
    perms = frozenset({Permission.OPPORTUNITIES_MODERATE}) if grant else frozenset()
    e.w.store.assignments[helper] = (
        Assignment(
            id=new_id(),
            user_id=helper,
            role=StaffRole(
                id=new_id(),
                kind=kind,
                name="Opportunity helper",
                name_i18n={},
                permissions=perms,
                is_builtin=False,
            ),
            scope_kind="all",
            scope_ref=None,
            starts_at=NOW - dt.timedelta(days=1),
            expires_at=None,
            granted_by=None,
        ),
    )
    return await e.w.ctx(helper, Role.COUNSELOR)


async def test_helper_moderator_approves_and_rejects_student_posts() -> None:
    e = Env()
    subj = await e.seed_subject()
    helper = await _helper_ctx(e, grant=True)
    assert e.svc.can_moderate(helper)
    first = await e.svc.submit(await e.student(), _draft(subj))
    second = await e.svc.submit(await e.student(), _draft(subj, title="IELTS"))
    assert first.status == "pending" and first.submitter_role == "student"
    assert {s.id for s in await e.svc.submissions(helper, status="pending")} == {
        first.id,
        second.id,
    }
    done = await e.svc.review(
        helper, first.id, approve=True, reason=None, lock_version=first.lock_version
    )
    assert done.status == "approved" and done.applied_id is not None
    rej = await e.svc.review(
        helper, second.id, approve=False, reason="dup", lock_version=0
    )
    assert rej.status == "rejected"


async def test_staff_without_the_grant_cannot_moderate() -> None:
    e = Env()
    subj = await e.seed_subject()
    plain = await _helper_ctx(e, grant=False)
    assert not e.svc.can_moderate(plain)
    sub = await e.svc.submit(await e.student(), _draft(subj))
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.review(plain, sub.id, approve=True, reason=None, lock_version=0)


async def test_grant_does_not_help_a_student_holding_it() -> None:
    e = Env()
    subj = await e.seed_subject()
    helper = await _helper_ctx(e, grant=True)
    student_with_grant = await e.w.ctx(helper.actor.user_id, Role.STUDENT)
    assert not e.svc.can_moderate(student_with_grant)
    sub = await e.svc.submit(await e.student(), _draft(subj))
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.review(
            student_with_grant, sub.id, approve=True, reason=None, lock_version=0
        )


async def test_student_submissions_are_rate_limited_but_staff_are_not() -> None:
    e = Env()
    subj = await e.seed_subject()
    limiter = CountingLimiter()
    svc = OpportunityService(
        e.uow, e.w.policy, FixedClock(NOW), limiter=limiter  # type: ignore[arg-type]
    )
    st = await e.student()
    for _ in range(STUDENT_SUBMIT_LIMIT):
        await svc.submit(st, _draft(subj))
    with pytest.raises(RateLimitedError):
        await svc.submit(st, _draft(subj))
    for _ in range(STUDENT_SUBMIT_LIMIT + 2):
        await svc.submit(await e.admin(), _draft(subj))
    assert all(str(STUDENT) in k for k in limiter.keys)


async def test_taxonomy_levels_and_in_use_delete() -> None:
    e = Env()
    subj = await e.seed_subject()
    a = await e.admin()
    with pytest.raises(ValidationFailedError):
        await e.svc.save_node(
            a,
            node_id=None,
            level="subject",
            parent_id=None,
            names={"en": "X"},
            position=0,
        )
    s = await e.svc.submit(a, _draft(subj))
    await e.svc.review(a, s.id, approve=True, reason=None, lock_version=0)
    with pytest.raises(InvalidTransitionError):
        await e.svc.delete_node(a, subj)
    [field] = await e.svc.taxonomy()
    assert field.subfields[0].subjects[0].id == subj


async def test_plan_owner_only_and_staff_plan_read_needs_scope() -> None:
    e = Env()
    subj = await e.seed_subject()
    a = await e.admin()
    s = await e.svc.submit(a, _draft(subj))
    oid = await e.svc.review(a, s.id, approve=True, reason=None, lock_version=0)
    assert oid.applied_id is not None
    st = await e.student()
    await e.svc.save_to_plan(st, oid.applied_id, planned_grade=10, note=None)
    view = await e.svc.plan_of(st, STUDENT)
    assert len(view.entries) == 1 and view.analytics.unplaced == 0
    with pytest.raises(AdmissionForbiddenError):
        await e.svc.save_to_plan(a, oid.applied_id, planned_grade=10, note=None)
    with pytest.raises(AdmissionNotFoundError):
        await e.svc.plan_of(await e.w.ctx(STAFF, Role.COUNSELOR), STUDENT)
    end = NOW.date() + dt.timedelta(days=400)
    [d] = await e.svc.deadlines_for(STUDENT, NOW.date(), end)
    assert d.projected and d.day.month == 10 and d.day.day == 5


# - - - Recurrence - - -


def test_rule_and_projection() -> None:
    rule = parse_rule("FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=3")
    got = occurrences(rule, dt.date(2020, 5, 3), dt.date(2026, 1, 1), 2)
    assert got == [dt.date(2026, 5, 3), dt.date(2027, 5, 3)]
    with pytest.raises(ValueError):
        parse_rule("FREQ=HOURLY")
    today = dt.date(2026, 6, 1)
    assert expected_this_cycle([dt.date(2025, 3, 1)], today) == [dt.date(2027, 3, 1)]
    assert expected_this_cycle([dt.date(2025, 9, 1)], today) == [dt.date(2026, 9, 1)]
    assert expected_this_cycle([dt.date(2024, 2, 29)], dt.date(2027, 1, 1)) == [
        dt.date(2027, 2, 28)
    ]


def test_announced_dates_win_over_projection() -> None:
    today = dt.date(2026, 6, 1)
    d = _draft(new_id(), exam_dates=(dt.date(2026, 10, 1),))
    events = upcoming_dates(d, today, today + dt.timedelta(days=365))
    assert [(e.day, e.projected) for e in events] == [(dt.date(2026, 10, 1), False)]


# - - - Planner - - -


async def test_planner_fake_output_places_every_saved_entry() -> None:
    e = Env()
    subj = await e.seed_subject()
    a = await e.admin()
    ids = []
    for title in ("SAT", "IELTS"):
        s = await e.svc.submit(a, _draft(subj, title=title))
        r = await e.svc.review(a, s.id, approve=True, reason=None, lock_version=0)
        assert r.applied_id is not None
        ids.append(r.applied_id)
    st = await e.student()
    await e.svc.save_to_plan(st, ids[0], planned_grade=None, note=None)
    await e.svc.save_to_plan(st, ids[1], planned_grade=11, note=None)
    view = await e.svc.plan_of(st, STUDENT)
    bogus = {"steps": [{"opportunity_id": str(new_id()), "grade": 9, "term": "x"}]}
    plan = place_rest(clean_plan(bogus, {str(i) for i in ids}, 10, NOW), view, 10)
    assert isinstance(plan, AiPlan)
    by = {s.opportunity_id: s for s in plan.steps}
    assert set(by) == set(ids)
    assert by[ids[0]].grade == 10 and by[ids[1]].grade == 11
    assert all(s.term in ("fall", "spring", "summer") for s in plan.steps)


async def test_planner_refuses_without_ai_consent() -> None:
    e = Env()
    planner = OpportunityPlanner(
        e.uow,  # type: ignore[arg-type]
        e.w.policy,
        e.svc,
        None,  # type: ignore[arg-type]
        FakeConsents({}),
        FixedClock(NOW),
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    with pytest.raises(ConsentRequiredError):
        await planner.generate(await e.student(), "en", interests="", career="")
    with pytest.raises(AdmissionForbiddenError):
        await planner.generate(await e.admin(), "en", interests="", career="")


@pytest.mark.parametrize("offset", [-10, 400])
async def test_calendar_deadlines_respect_requested_range(offset: int) -> None:
    e = Env()
    subject = await e.seed_subject()
    admin = await e.admin()
    day = NOW.date() + dt.timedelta(days=offset)
    submission = await e.svc.submit(
        admin,
        _draft(subject, registration_deadlines=(day,), last_year_dates=()),
    )
    reviewed = await e.svc.review(
        admin, submission.id, approve=True, reason=None, lock_version=0
    )
    assert reviewed.applied_id is not None
    await e.svc.save_to_plan(
        await e.student(), reviewed.applied_id, planned_grade=None, note=None
    )

    deadlines = await e.svc.deadlines_for(STUDENT, day, day)

    assert [deadline.day for deadline in deadlines] == [day]
    assert (
        await e.svc.deadlines_for(
            STUDENT, day + dt.timedelta(days=1), day + dt.timedelta(days=2)
        )
        == []
    )
