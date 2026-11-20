"""Items slice: CRUD, review cache and quota, and the interview rounds."""

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.interview import (
    MAX_ROUNDS,
    ItemInterviewService,
)
from app.modules.admission.application.item_grade import ItemGradeService
from app.modules.admission.application.items import ItemService, MetricDraft
from app.modules.admission.application.review import ItemReviewService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
    ConsentRequiredError,
    InvalidAnswerError,
    ItemIncompleteError,
    ItemLimitError,
    ProjectedDateRequiredError,
    QuotaExceededError,
)
from app.modules.admission.domain.items import MAX_DRAFTS, MAX_HONORS, Item, ItemGrade
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.ports.consent import AI, STAFF_VIEW
from app.modules.admission.ports.items import (
    InterviewRound,
    Metric,
    ProfileWordsRef,
    StoredReview,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeConsents,
    FakeMembership,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

import pytest

STUDENT = new_id()
OTHER = new_id()
GROUP = new_id()


class ItemsData:
    """In-memory state of the items repository, shared across transactions."""

    def __init__(self) -> None:
        self.items: dict[UUID, Item] = {}
        self.metrics: dict[UUID, list[Metric]] = {}
        self.rounds: dict[UUID, list[InterviewRound]] = {}
        self.reviews: list[StoredReview] = []
        self.feedback: list[tuple[UUID, str]] = []
        self.words: dict[UUID, ProfileWordsRef] = {}
        self.dismissed: dict[UUID, set[UUID]] = {}


class MemItems:
    """An ItemRepository over ItemsData."""

    def __init__(self, d: ItemsData) -> None:
        self.d = d

    async def list_for(self, student_id: UUID) -> list[Item]:
        rows = [i for i in self.d.items.values() if i.student_id == student_id]
        return sorted(rows, key=lambda i: (i.kind, i.position))

    async def get(self, item_id: UUID) -> Item | None:
        return self.d.items.get(item_id)

    async def add(self, item: Item) -> Item:
        self.d.items[item.id] = item
        return item

    async def update(self, item: Item) -> Item:
        stored = replace(item, lock_version=item.lock_version + 1)
        self.d.items[item.id] = stored
        return stored

    async def delete(self, item_id: UUID) -> None:
        self.d.items.pop(item_id, None)
        self.d.metrics.pop(item_id, None)

    async def set_order(self, ordered: Sequence[UUID]) -> None:
        for n, i in enumerate(ordered):
            self.d.items[i] = replace(self.d.items[i], position=n)

    async def dismissed_certificates(self, student_id: UUID) -> set[UUID]:
        return set(self.d.dismissed.get(student_id, set()))

    async def dismiss_certificate(self, student_id: UUID, entry_id: UUID) -> None:
        self.d.dismissed.setdefault(student_id, set()).add(entry_id)

    async def set_grade(self, item_id: UUID, grade: ItemGrade) -> None:
        self.d.items[item_id] = replace(self.d.items[item_id], grade=grade)

    async def metrics_for(self, item_ids: Sequence[UUID]) -> dict[UUID, list[Metric]]:
        return {i: list(self.d.metrics.get(i, [])) for i in item_ids}

    async def replace_metrics(self, item_id: UUID, metrics: Sequence[Metric]) -> None:
        self.d.metrics[item_id] = list(metrics)

    async def interviews(self, item_id: UUID) -> list[InterviewRound]:
        return list(self.d.rounds.get(item_id, []))

    async def add_interview(self, round_: InterviewRound) -> InterviewRound:
        self.d.rounds.setdefault(round_.item_id, []).append(round_)
        return round_

    async def update_round(
        self,
        round_id: UUID,
        *,
        questions: dict[str, Any] | None = None,
        answers: dict[str, Any] | None = None,
    ) -> None:
        for rounds in self.d.rounds.values():
            for n, r in enumerate(rounds):
                if r.id == round_id:
                    rounds[n] = replace(
                        r,
                        questions=r.questions if questions is None else questions,
                        answers=r.answers if answers is None else answers,
                    )

    async def clear_interviews(self, item_id: UUID) -> None:
        self.d.rounds.pop(item_id, None)

    async def words(self, student_id: UUID) -> ProfileWordsRef | None:
        return self.d.words.get(student_id)

    async def find_review(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> StoredReview | None:
        return next(
            (
                r
                for r in self.d.reviews
                if r.target_id == target_id and r.input_hash == input_hash
            ),
            None,
        )

    async def latest_review(
        self, target_kind: str, target_id: UUID
    ) -> StoredReview | None:
        rows = [r for r in self.d.reviews if r.target_id == target_id]
        return rows[-1] if rows else None

    async def get_review(self, review_id: UUID) -> StoredReview | None:
        return next((r for r in self.d.reviews if r.id == review_id), None)

    async def add_review(self, review: StoredReview) -> StoredReview:
        stored = replace(review, created_at=NOW)
        self.d.reviews.append(stored)
        return stored

    async def count_reviews(
        self, student_id: UUID, task: str, since: dt.datetime, *, target_id: UUID | None
    ) -> int:
        return sum(
            1
            for r in self.d.reviews
            if r.student_id == student_id
            and (target_id is None or r.target_id == target_id)
        )

    async def add_feedback(
        self, review_id: UUID, student_id: UUID, kind: str, note: str | None
    ) -> None:
        self.d.feedback.append((review_id, kind))


def _per_day(value: int) -> Any:
    async def read(user_id: UUID) -> int | None:
        return value

    return read


class ItemsUow(FakeUow):
    """FakeUow with the items repository."""

    def __init__(self, s: FakeStore, d: ItemsData) -> None:
        super().__init__(s)
        self.items = MemItems(d)


class ScriptAi:
    """StructuredAi that returns queued replies and records the calls."""

    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def json(self, **kw: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kw)
        return self.replies.pop(0), "fake/model"


def _rewrite(desc: str = "Led weekly builds for club members") -> dict[str, Any]:
    return {
        "position": "Captain",
        "org": "Robotics",
        "description": desc,
        "claim_refs": [],
    }


def _review(impact: str = "A", evidence: str = "clear", **kw: Any) -> dict[str, Any]:
    return {
        "dimensions": [
            {
                "dim": d,
                "evidence": evidence,
                "grade": impact if d == "impact" else "B",
                "suggestion": "s",
            }
            for d in ("clarity", "role_name", "impact", "alignment")
        ],
        "word_fit": [{"word": "curious", "fit": "some", "evidence": "e"}],
        "rewrite": _rewrite(),
        "missing_facts": ["How many members?"],
        "injection_suspected": False,
        "safeguarding": False,
    } | kw


def _interview(questions: int = 2, ready: bool = False) -> dict[str, Any]:
    q = {
        "gap": "numbers",
        "question": "How many?",
        "why_it_matters": "scale",
        "options": [],
    }
    return {
        "questions": [q] * questions,
        "ready_for_review": ready,
        "proposal": _rewrite(),
        "injection_suspected": False,
        "safeguarding": False,
    }


class World:
    def __init__(self, *replies: dict[str, Any], per_day: int = 60) -> None:
        self.store = FakeStore()
        self.data = ItemsData()
        self.data.words[STUDENT] = ProfileWordsRef(("curious", "kind", "bold"), 1)
        membership = FakeMembership(
            [student_ref(STUDENT, GROUP), student_ref(OTHER, GROUP)]
        )
        uow = lambda: ItemsUow(self.store, self.data)  # noqa: E731
        self.consents = FakeConsents({STUDENT: frozenset({STAFF_VIEW, AI})})
        self.policy = AccessPolicy(
            uow,
            membership,
            self.consents,
            FixedClock(NOW),
            {10, 11},
        )
        self.resolver = ResolveAdmissionActor(
            uow, membership, FixedClock(NOW), {10, 11}
        )
        self.ai = ScriptAi(*replies)
        self.items = ItemService(uow, self.policy)
        self.reviews = ItemReviewService(
            uow,
            self.policy,
            self.ai,
            self.consents,
            FixedClock(NOW),
            BuiltinPrompts(),
            per_day=_per_day(per_day),
            per_item=2,
        )
        self.interviews = ItemInterviewService(
            uow, self.policy, self.ai, self.consents, BuiltinPrompts()
        )

    async def ctx(self, user_id: UUID = STUDENT) -> AdmissionContext:
        return await self.resolver.execute(Actor(user_id, frozenset({Role.STUDENT})))

    async def item(self, kind: str = "activity", **kw: Any) -> Item:
        draft = Item(
            new_id(), STUDENT, kind, "Captain", "Robotics", "Built robots", **kw
        )
        return (await self.items.create(await self.ctx(), draft)).item


def _ready_honor(**kw: Any) -> Item:
    return Item(
        new_id(),
        STUDENT,
        "honor",
        "Winner",
        "Olympiad",
        "",
        category="award",
        level="national",
        grades=(11,),
        status="ready",
        **kw,
    )


def _bare() -> Item:
    return Item(new_id(), STUDENT, "honor", "Idea", "", "")


async def test_create_caps_and_positions() -> None:
    w = World()
    ctx = await w.ctx()
    first = (await w.items.create(ctx, _ready_honor())).item
    for _ in range(MAX_HONORS - 1):
        await w.items.create(ctx, _ready_honor())
    with pytest.raises(ItemLimitError):
        await w.items.create(ctx, _ready_honor())
    assert first.position == 0
    assert max(i.position for i in w.data.items.values()) == MAX_HONORS - 1


async def test_draft_needs_only_title_and_ignores_ready_cap() -> None:
    w = World()
    ctx = await w.ctx()
    for _ in range(MAX_HONORS):
        await w.items.create(ctx, _ready_honor())
    view = await w.items.create(ctx, _bare())
    assert view.item.status == "draft"


async def test_drafts_are_capped() -> None:
    w = World()
    ctx = await w.ctx()
    for _ in range(MAX_DRAFTS):
        await w.items.create(ctx, _bare())
    with pytest.raises(ItemLimitError):
        await w.items.create(ctx, _bare())


async def test_ready_requires_complete_fields() -> None:
    w = World()
    ctx = await w.ctx()
    ready = replace(_bare(), status="ready")
    with pytest.raises(ItemIncompleteError) as err:
        await w.items.create(ctx, ready)
    assert set(err.value.params["fields"]) == {"category", "level", "grades"}
    draft = (await w.items.create(ctx, _bare())).item
    with pytest.raises(ItemIncompleteError):
        await w.items.update(ctx, draft.id, {"status": "ready"}, draft.lock_version)
    done = await w.items.update(
        ctx,
        draft.id,
        {"status": "ready", "category": "award", "level": "school", "grades": (10,)},
        draft.lock_version,
    )
    assert done.status == "ready"


async def test_draft_to_ready_respects_cap() -> None:
    w = World()
    ctx = await w.ctx()
    for _ in range(MAX_HONORS):
        await w.items.create(ctx, _ready_honor())
    draft = (await w.items.create(ctx, _bare())).item
    changes = {
        "status": "ready",
        "category": "award",
        "level": "school",
        "grades": (10,),
    }
    with pytest.raises(ItemLimitError):
        await w.items.update(ctx, draft.id, changes, draft.lock_version)


async def test_projected_metric_needs_target_date() -> None:
    w = World()
    item = await w.item()
    ctx = await w.ctx()
    with pytest.raises(ProjectedDateRequiredError):
        await w.items.set_metrics(
            ctx, item.id, [MetricDraft("Members", Decimal(40), horizon="projected")]
        )
    rows = await w.items.set_metrics(
        ctx,
        item.id,
        [
            MetricDraft(
                "Members",
                Decimal(40),
                horizon="projected",
                target_date=dt.date(2027, 5, 1),
            )
        ],
    )
    assert rows[0].target_date == dt.date(2027, 5, 1)


async def test_update_lock_conflict_and_foreign_item() -> None:
    w = World()
    item = await w.item()
    ctx = await w.ctx()
    updated = await w.items.update(ctx, item.id, {"title": "Founder"}, 0)
    assert updated.title == "Founder" and updated.lock_version == 1
    with pytest.raises(AdmissionConflictError):
        await w.items.update(ctx, item.id, {"title": "X"}, 0)
    with pytest.raises(AdmissionNotFoundError):
        await w.items.delete(await w.ctx(OTHER), item.id)


async def test_order_rejects_unknown_ids() -> None:
    w = World()
    a, b = await w.item(), await w.item()
    ctx = await w.ctx()
    await w.items.order(ctx, [b.id, a.id])
    assert w.data.items[b.id].position == 0
    with pytest.raises(AdmissionNotFoundError):
        await w.items.order(ctx, [a.id, new_id()])


async def test_review_caches_and_marks_stale() -> None:
    w = World(_review())
    item = await w.item()
    ctx = await w.ctx()
    first = await w.reviews.review(ctx, item.id, "en")
    again = await w.reviews.review(ctx, item.id, "en")
    assert again.id == first.id and len(w.ai.calls) == 1
    assert [d.user_id for d in w.store.notifications] == [STUDENT]
    assert first.overall is not None
    [view] = await w.items.list_items(ctx, STUDENT)
    assert not view.stale
    await w.items.update(ctx, item.id, {"description": "Built six robots"}, 0)
    [view] = await w.items.list_items(ctx, STUDENT)
    assert view.stale


async def test_review_quota_per_item() -> None:
    w = World(_review(), _review())
    item = await w.item()
    ctx = await w.ctx()
    await w.reviews.review(ctx, item.id, "en")
    await w.reviews.review(ctx, item.id, "ru")
    with pytest.raises(QuotaExceededError):
        await w.reviews.review(ctx, item.id, "uz")


async def test_projected_numbers_cap_impact() -> None:
    w = World(_review(impact="A", evidence="will reach 40 members"))
    item = await w.item()
    ctx = await w.ctx()
    await w.items.set_metrics(
        ctx,
        item.id,
        [
            MetricDraft(
                "Members",
                Decimal(40),
                horizon="projected",
                target_date=dt.date(2027, 5, 1),
            )
        ],
    )
    review = await w.reviews.review(ctx, item.id, "en")
    assert review.grades["impact"] == "C"


async def test_safeguarding_review_has_no_grades() -> None:
    w = World(_review(safeguarding=True))
    item = await w.item()
    review = await w.reviews.review(await w.ctx(), item.id, "en")
    assert review.safety_flag == "safeguarding" and review.grades == {}


async def test_interview_ends_after_three_rounds_with_proposal() -> None:
    w = World(_interview(), _interview(), _interview(), _interview(0, True))
    item = await w.item()
    ctx = await w.ctx()
    state = await w.interviews.step(ctx, item.id, {}, "en")
    for n in range(MAX_ROUNDS - 1):
        assert not state.ready and len(state.rounds) == n + 1
        state = await w.interviews.step(ctx, item.id, {"0": "about 20"}, "en")
    assert len(state.rounds) == MAX_ROUNDS and not state.ready
    state = await w.interviews.step(ctx, item.id, {"0": "20 members"}, "en")
    assert state.ready and state.proposal is not None
    assert len(state.rounds) == MAX_ROUNDS
    again = await w.interviews.step(ctx, item.id, {}, "en")
    assert again.ready and len(w.ai.calls) == MAX_ROUNDS + 1


@pytest.mark.parametrize("granted", [None, frozenset({STAFF_VIEW})])
async def test_review_and_interview_need_ai_consent(
    granted: frozenset[str] | None,
) -> None:
    w = World(_review(), _interview())
    item = await w.item()
    ctx = await w.ctx()
    # None: never given; a set without AI: given once, then withdrawn.
    if granted is None:
        w.consents.grants.pop(STUDENT)
    else:
        w.consents.grants[STUDENT] = granted
    with pytest.raises(ConsentRequiredError):
        await w.reviews.review(ctx, item.id, "en")
    with pytest.raises(ConsentRequiredError):
        await w.interviews.step(ctx, item.id, {}, "en")
    assert w.ai.calls == []


class _NoLimit:
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        return None


def _grader(w: World) -> ItemGradeService:
    return ItemGradeService(
        lambda: ItemsUow(w.store, w.data),
        w.policy,
        w.ai,
        w.consents,
        BuiltinPrompts(),
        _NoLimit(),  # type: ignore[arg-type]
        _per_day(10),
    )


def _graded(**kw: str) -> dict[str, Any]:
    return {
        "title_grade": "B",
        "title_tip": "Name the role.",
        "description_grade": "C",
        "description_tip": "Add a number.",
    } | kw


async def test_grade_is_cached_by_content_and_locale() -> None:
    w = World(_graded(), _graded(), _graded())
    grader = _grader(w)
    ctx = await w.ctx()
    item = await w.item()
    first = await grader.grade(ctx, item.id, "en")
    again = await grader.grade(ctx, item.id, "en")
    assert first == again and len(w.ai.calls) == 1
    stored = w.data.items[item.id]
    assert stored.grade == first and not stored.grade_stale
    await grader.grade(ctx, item.id, "ru")
    assert len(w.ai.calls) == 2
    changed = replace(w.data.items[item.id], description="Led 40 members")
    w.data.items[item.id] = changed
    assert changed.grade_stale
    await grader.grade(ctx, item.id, "ru")
    assert len(w.ai.calls) == 3


async def test_grade_rules() -> None:
    w = World(_graded(title_grade="Z"))
    grader = _grader(w)
    item = await w.item()
    with pytest.raises(AdmissionNotFoundError):
        await grader.grade(await w.ctx(OTHER), item.id, "en")
    with pytest.raises(AiInvalidOutputError):
        await grader.grade(await w.ctx(), item.id, "en")
    assert w.data.items[item.id].grade is None
    w.consents.grants[STUDENT] = frozenset({STAFF_VIEW})
    with pytest.raises(ConsentRequiredError):
        await grader.grade(await w.ctx(), item.id, "en")


async def test_move_honor_between_columns_and_reorder() -> None:
    w = World()
    ctx = await w.ctx()
    a = (await w.items.create(ctx, _ready_honor())).item
    b = (await w.items.create(ctx, _ready_honor())).item
    draft = (await w.items.create(ctx, _bare())).item
    await w.items.move(ctx, b.id, "ready", 0)
    assert w.data.items[b.id].position == 0 and w.data.items[a.id].position == 1
    await w.items.move(ctx, a.id, "draft", 0)
    assert w.data.items[a.id].status == "draft"
    assert w.data.items[a.id].position == 0 and w.data.items[draft.id].position == 1
    with pytest.raises(ItemIncompleteError):
        await w.items.move(ctx, draft.id, "ready", 0)


async def test_move_honor_to_ready_respects_cap() -> None:
    w = World()
    ctx = await w.ctx()
    for _ in range(MAX_HONORS):
        await w.items.create(ctx, _ready_honor())
    spare = (await w.items.create(ctx, replace(_ready_honor(), status="draft"))).item
    with pytest.raises(ItemLimitError):
        await w.items.move(ctx, spare.id, "ready", 0)


async def test_item_validation_of_category_hours_and_grades() -> None:
    w = World()
    ctx = await w.ctx()
    for kw in (
        {"category": "national"},
        {"level": "state_regional"},
        {"hours_per_week": 169},
        {"weeks_per_year": 53},
        {"grades": (8,)},
    ):
        bad = Item(new_id(), STUDENT, "honor", "Win", "", "", **kw)
        with pytest.raises(InvalidAnswerError):
            await w.items.create(ctx, bad)
    ok = Item(new_id(), STUDENT, "activity", "Club", "", "", category="stem_research")
    assert (await w.items.create(ctx, ok)).item.category == "stem_research"
