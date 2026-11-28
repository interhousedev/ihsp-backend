"""Badge authoring, preview, backfill and award events with fakes (spec 2.6).

The implementation must provide:
  app.modules.lms.application.badge_authoring:
    ListBadgeTemplates().execute(scope) -> templates
    CreateBadgeFromTemplate(repo, audit, backfill_queue, access).execute(actor,
    course_id, template, params, design)
      -> Badge; rejects past MAX_BADGES_PER_COURSE (BadgeInvalidError field 'limit');
      audits; enqueues backfill
    PreviewBadge(facts_reader, access).execute(actor, course_id, rule)
      -> PreviewView(would_earn, sample, examined, total, truncated)
      (examines at most PREVIEW_CAP == 2000 enrolments; `total` is the exact enrolment
      count from a bounded aggregate; when total > examined, truncated is True and
      would_earn is a LOWER BOUND of the eventual awards)
    UpdateBadge(repo, audit, backfill_queue, access).execute(actor, badge_id, rule=None,
    enabled=None)
      (a rule change enqueues backfill; existing awards stay)
    SetBadgeEnabled(...), CreatePlatformBadge(repo, audit, backfill_queue) (LMS_ADMIN
    only)
  app.modules.lms.application.badge_awarding:
    BackfillBadge(repo, facts_reader, awards, queue, batch=500, platform_facts=None)
      .execute(badge_id, cursor=None) -> BackfillResult(next_cursor, awarded)
      ONE bounded batch per execution (batch=500); when more rows remain it re-enqueues
      itself with `queue.enqueue(badge_id, cursor)`; idempotent; resumable; disabled or
      changed badges are re-read each batch (a disabled badge awards nothing).
      Platform badges read `platform_facts.page(cursor, limit)` -> [(user_id,
      PlatformFacts
      (level, coach_resolved, courses_completed))], eligible = every active user.
    `awards.award(badge_id, user_id, at, event)` writes the award AND its
      'lms.badge_awarded' outbox row {user_id, badge_id, course_id} in ONE transaction
      (returns False, writes nothing when the award exists). A crash between the two
      is impossible by construction; the real-DB rollback test is in the spec exit list.
  ports (app.modules.lms.ports.badge_repository, extended):
    BadgeRepository: add/get/update/count_for_course
    EnrolmentFacts: page(course_id, cursor, limit) -> (list[(user_id, LearnerFacts)],
    next_cursor)
    AwardStore: award(badge_id, user_id, at) -> bool (False when already awarded)
    BackfillQueue: enqueue(badge_id, cursor=None)
    CourseAccess: require_edit(actor, course_id) (staff EDIT of ONE course;
    ForbiddenError)
Test-local fakes define these shapes. Actors are the real app.shared.actor.Actor; course
EDIT is a per-course gate.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.badge_authoring import (
    PREVIEW_CAP,
    CreateBadgeFromTemplate,
    CreatePlatformBadge,
    PreviewBadge,
    UpdateBadge,
)
from app.modules.lms.application.badge_awarding import BackfillBadge
from app.modules.lms.domain.badge_model import Badge, BadgeScope
from app.modules.lms.domain.badges import (
    MAX_BADGES_PER_COURSE,
    BadgeInvalidError,
    LearnerFacts,
)
from app.shared.actor import Actor as RealActor
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)
NAME = {"uz": "a", "ru": "b", "en": "c"}
DESIGN = {
    "name": NAME,
    "description": {"en": "d"},
    "icon": "star",
    "color": "#336699",
    "shape": "circle",
}


def Actor(edit: bool = True, admin: bool = False) -> RealActor:  # noqa: N802
    """`edit` only matters through the Access fake below (staff of the course)."""
    roles = {Role.LMS_ADMIN} if admin else {Role.TEACHER}
    return RealActor(user_id=uuid4(), roles=frozenset(roles))


class Access:
    """Per-course EDIT gate: `allowed=None` lets every course through."""

    def __init__(self, allowed: set[UUID] | None = None) -> None:
        self.allowed = allowed

    async def require_edit(self, actor: RealActor, course_id: UUID) -> None:
        if self.allowed is not None and course_id not in self.allowed:
            raise ForbiddenError()


ACCESS = Access()
DENY = Access(set())


class Repo:
    def __init__(self) -> None:
        self.rows: dict[UUID, Badge] = {}

    async def add(self, b: Badge) -> None:
        self.rows[b.id] = b

    async def get(self, id: UUID) -> Badge | None:
        return self.rows.get(id)

    async def update(self, b: Badge) -> None:
        self.rows[b.id] = b

    async def count_for_course(self, course_id: UUID) -> int:
        return sum(1 for b in self.rows.values() if b.course_id == course_id)


class Queue:
    def __init__(self) -> None:
        self.jobs: list[UUID] = []
        self.cursors: list[int | None] = []

    async def enqueue(self, badge_id: UUID, cursor: int | None = None) -> None:
        self.jobs.append(badge_id)
        self.cursors.append(cursor)


class Audit:
    def __init__(self) -> None:
        self.rows: list[str] = []

    async def write(self, type: str, **kw: Any) -> None:
        self.rows.append(type)


class Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []


class Awards:
    """Award and outbox row are one atomic write, as in the real store."""

    def __init__(self, events: Events | None = None) -> None:
        self.rows: set[tuple[UUID, UUID]] = set()
        self.events = events or Events()

    async def award(
        self, badge_id: UUID, user_id: UUID, at: datetime, event: dict[str, Any]
    ) -> bool:
        key = (badge_id, user_id)
        if key in self.rows:
            return False
        self.rows.add(key)
        self.events.published.append(("lms.badge_awarded", event))
        return True


def facts(done_step: UUID | None) -> LearnerFacts:
    t = datetime(2026, 11, 1, tzinfo=UTC)
    return LearnerFacts(
        enrolled_at=t,
        course_completed_at=None,
        sections=[],
        completed_steps={done_step: t} if done_step else {},
        step_scores={},
        passed_tests=[],
        exam_scores=[],
        active_days=[],
        today=date(2026, 11, 27),
        reviews_per_day={},
    )


class Learners:
    """n learners; those with index < earners have completed a step."""

    def __init__(self, n: int, earners: int) -> None:
        self.rows = [
            (uuid4(), facts(uuid4() if i < earners else None)) for i in range(n)
        ]
        self.pages = 0

    async def total(self, course_id: UUID) -> int:
        return len(self.rows)

    async def page(self, course_id: UUID, cursor: int | None, limit: int):
        self.pages += 1
        start = cursor or 0
        chunk = self.rows[start : start + limit]
        nxt = start + limit if start + limit < len(self.rows) else None
        return chunk, nxt


async def _create(
    repo: Repo,
    queue: Queue,
    course: UUID,
    actor: RealActor | None = None,
    access: Access | None = None,
) -> Any:
    return await CreateBadgeFromTemplate(
        repo, Audit(), queue, access or ACCESS
    ).execute(actor or Actor(), course, "first_lesson", {}, DESIGN)


async def test_create_from_template_stores_rule_audits_and_queues_backfill() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    assert b.template_code == "first_lesson" and b.rule["event"] == "step_completed"
    assert b.scope == BadgeScope.COURSE and b.course_id == course
    assert queue.jobs == [b.id]


async def test_create_needs_course_edit_permission() -> None:
    with pytest.raises(ForbiddenError):
        await _create(Repo(), Queue(), uuid4(), Actor(edit=False), DENY)


async def test_create_is_rejected_over_the_course_limit() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    for _ in range(MAX_BADGES_PER_COURSE):
        await _create(repo, queue, course)
    with pytest.raises(BadgeInvalidError):
        await _create(repo, queue, course)
    assert await repo.count_for_course(course) == MAX_BADGES_PER_COURSE


async def test_platform_badge_is_lms_admin_only() -> None:
    repo, queue = Repo(), Queue()
    rule = {"event": "level_reached", "condition": {"op": "count_gte", "value": 5}}
    with pytest.raises(ForbiddenError):
        await CreatePlatformBadge(repo, Audit(), queue).execute(
            Actor(edit=True), rule, DESIGN
        )
    b = await CreatePlatformBadge(repo, Audit(), queue).execute(
        Actor(admin=True), rule, DESIGN
    )
    assert b.scope == BadgeScope.PLATFORM and b.course_id is None


async def test_rule_change_enqueues_a_backfill_but_a_rename_does_not() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    queue.jobs.clear()
    await UpdateBadge(repo, Audit(), queue, ACCESS).execute(
        Actor(), b.id, enabled=False
    )
    assert queue.jobs == []
    await UpdateBadge(repo, Audit(), queue, ACCESS).execute(
        Actor(), b.id, rule={"event": "course_completed", "condition": None}
    )
    assert queue.jobs == [b.id] and repo.rows[b.id].version == 2


async def test_preview_counts_without_awarding() -> None:
    learners = Learners(10, earners=4)
    out = await PreviewBadge(learners, ACCESS).execute(
        Actor(), uuid4(), {"event": "step_completed", "condition": None}
    )
    assert out.would_earn == 4 and len(out.sample) <= 4


async def test_preview_over_the_cap_is_a_flagged_lower_bound() -> None:
    n = PREVIEW_CAP + 500
    out = await PreviewBadge(Learners(n, earners=n), ACCESS).execute(
        Actor(), uuid4(), {"event": "step_completed", "condition": None}
    )
    assert out.would_earn == PREVIEW_CAP and out.examined == PREVIEW_CAP
    assert out.total == n and out.truncated is True


async def test_preview_under_the_cap_is_exact_and_not_truncated() -> None:
    out = await PreviewBadge(Learners(10, 4), ACCESS).execute(
        Actor(), uuid4(), {"event": "step_completed", "condition": None}
    )
    assert (out.examined, out.total, out.truncated) == (10, 10, False)


async def test_preview_and_update_are_scoped_to_the_course() -> None:
    mine, other = uuid4(), uuid4()
    access = Access({mine})
    rule = {"event": "step_completed", "condition": None}
    with pytest.raises(ForbiddenError):
        await PreviewBadge(Learners(1, 1), access).execute(Actor(), other, rule)
    repo, queue = Repo(), Queue()
    b = await _create(repo, queue, other)
    with pytest.raises(ForbiddenError):
        await UpdateBadge(repo, Audit(), queue, access).execute(
            Actor(), b.id, enabled=False
        )
    with pytest.raises(ForbiddenError):
        await _create(repo, queue, other, access=access)


async def test_course_editor_cannot_update_a_platform_badge() -> None:
    repo, queue = Repo(), Queue()
    rule = {"event": "level_reached", "condition": {"op": "count_gte", "value": 5}}
    b = await CreatePlatformBadge(repo, Audit(), queue).execute(
        Actor(admin=True), rule, DESIGN
    )
    with pytest.raises(ForbiddenError):
        await UpdateBadge(repo, Audit(), queue, ACCESS).execute(
            Actor(), b.id, enabled=False
        )


async def test_create_and_update_write_audit_rows() -> None:
    repo, queue, audit, course = Repo(), Queue(), Audit(), uuid4()
    actor = Actor()
    b = await CreateBadgeFromTemplate(repo, audit, queue, ACCESS).execute(
        actor, course, "first_lesson", {}, DESIGN
    )
    await UpdateBadge(repo, audit, queue, ACCESS).execute(actor, b.id, enabled=False)
    assert len(audit.rows) == 2


async def test_preview_rejects_an_invalid_rule() -> None:
    with pytest.raises(BadgeInvalidError):
        await PreviewBadge(Learners(1, 1), ACCESS).execute(
            Actor(), uuid4(), {"event": "x"}
        )


async def test_preview_count_equals_the_awards_a_backfill_makes() -> None:
    """Exit check of phase 4."""
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    learners = Learners(12, earners=5)
    preview = await PreviewBadge(learners, ACCESS).execute(Actor(), course, b.rule)
    awards = Awards()
    result = await BackfillBadge(repo, learners, awards, queue, batch=500).execute(b.id)
    assert result.awarded == preview.would_earn == 5 == len(awards.rows)
    assert preview.truncated is False


async def test_backfill_is_idempotent() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    learners, awards = Learners(8, 3), Awards()
    events = awards.events
    job = BackfillBadge(repo, learners, awards, queue, batch=500)
    await job.execute(b.id)
    again = await job.execute(b.id)
    assert again.awarded == 0 and len(awards.rows) == 3
    assert [n for n, _ in events.published].count("lms.badge_awarded") == 3


async def test_backfill_runs_one_bounded_batch_per_execution_and_requeues() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    queue.jobs.clear()
    queue.cursors.clear()
    learners, awards = Learners(1200, 1200), Awards()
    job = BackfillBadge(repo, learners, awards, queue, batch=500)
    first = await job.execute(b.id)
    assert first.awarded == 500 and first.next_cursor is not None
    assert queue.jobs == [b.id] and queue.cursors == [first.next_cursor]
    second = await job.execute(b.id, cursor=first.next_cursor)
    last = await job.execute(b.id, cursor=second.next_cursor)
    assert (second.awarded, last.awarded) == (500, 200) and last.next_cursor is None
    assert len(queue.jobs) == 2  # the final batch does not re-enqueue
    assert len(awards.rows) == 1200


async def test_preview_over_the_cap_is_below_the_eventual_awards() -> None:
    """Phase 4 exit, over the cap: preview is a flagged lower bound of the awards."""
    n = PREVIEW_CAP + 500
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    learners, awards = Learners(n, n), Awards()
    preview = await PreviewBadge(learners, ACCESS).execute(Actor(), course, b.rule)
    cursor: int | None = None
    while True:
        out = await BackfillBadge(repo, learners, awards, queue, batch=500).execute(
            b.id, cursor
        )
        if out.next_cursor is None:
            break
        cursor = out.next_cursor
    assert preview.truncated and preview.would_earn <= len(awards.rows) == preview.total


async def test_disabling_between_batches_stops_awarding() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    learners, awards = Learners(1000, 1000), Awards()
    job = BackfillBadge(repo, learners, awards, queue, batch=500)
    first = await job.execute(b.id)
    await UpdateBadge(repo, Audit(), queue, ACCESS).execute(
        Actor(), b.id, enabled=False
    )
    second = await job.execute(b.id, cursor=first.next_cursor)
    assert second.awarded == 0 and len(awards.rows) == 500


async def test_platform_backfill_uses_platform_facts() -> None:
    class PlatformFacts:
        def __init__(self) -> None:
            self.rows = [
                (
                    uuid4(),
                    SimpleNamespace(level=lv, coach_resolved=0, courses_completed=0),
                )
                for lv in (1, 4, 6, 9)
            ]

        async def page(self, cursor: int | None, limit: int):
            return self.rows, None

    repo, queue = Repo(), Queue()
    rule = {"event": "level_reached", "condition": {"op": "count_gte", "value": 5}}
    b = await CreatePlatformBadge(repo, Audit(), queue).execute(
        Actor(admin=True), rule, DESIGN
    )
    awards = Awards()
    out = await BackfillBadge(
        repo, Learners(0, 0), awards, queue, batch=500, platform_facts=PlatformFacts()
    ).execute(b.id)
    assert out.awarded == 2 == len(awards.rows)


async def test_backfill_skips_disabled_badges_and_never_revokes() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    awards = Awards()
    awards.rows.add((b.id, uuid4()))
    await UpdateBadge(repo, Audit(), queue, ACCESS).execute(
        Actor(), b.id, enabled=False
    )
    out = await BackfillBadge(repo, Learners(5, 5), awards, queue, batch=500).execute(
        b.id
    )
    assert out.awarded == 0 and len(awards.rows) == 1


async def test_awarding_publishes_badge_awarded_with_ids() -> None:
    repo, queue, course = Repo(), Queue(), uuid4()
    b = await _create(repo, queue, course)
    learners, awards = Learners(1, 1), Awards()
    events = awards.events
    await BackfillBadge(repo, learners, awards, queue, batch=500).execute(b.id)
    name, payload = events.published[0]
    assert name == "lms.badge_awarded"
    assert payload["badge_id"] == str(b.id) and payload["course_id"] == str(course)
    assert payload["user_id"] == str(learners.rows[0][0])
