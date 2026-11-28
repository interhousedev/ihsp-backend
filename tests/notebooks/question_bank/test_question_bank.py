"""Question bank keyed by EMIS subject and topic (spec 3.2a, "Question bank").

Studio draws a test FROM the bank (random shuffle) or saves generated questions TO it.
The bank is per EMIS subject (`emis_subject_id`, as in the curriculum) and topic.

The implementation must provide:
- `app.modules.notebooks.domain.question_bank`: `BankQuestion` frozen dataclass (id,
  owner_id, emis_subject_id: int, topic: str, question, answer, options: tuple[str,
  ...], explanation|None, difficulty "easy"|"medium"|"hard", origin "ai"|"teacher",
  visibility "teacher"|"subject", created_at); `question_key(text) -> str` (case,
  whitespace and trailing punctuation insensitive: the duplicate key).
- `app.modules.notebooks.ports.question_bank.QuestionBankStore`: `async add(q)`,
  `async list(emis_subject_id, topic|None) -> list[BankQuestion]`, `async get(id)`,
  `async replace(q)`.
- `app.modules.notebooks.application.question_bank.QuestionBankService(store, clock)`:
  - `save_generated(actor, *, emis_subject_id, topic, questions: Sequence[QuestionItem],
    difficulty="medium", origin="ai", visibility="teacher") -> SaveResult(saved,
    skipped)` skipping duplicates of the same subject+topic the actor can see;
    teachers and staff only (others ForbiddenError); empty topic or list ->
    ValidationFailedError.
  - `draw(actor, *, emis_subject_id, topic, count, difficulty=None, seed=None) ->
    list[BankQuestion]`: random without repeats from the actor's own questions plus
    other teachers' `subject` ones; same seed -> same order; fewer than `count` when
    the pool is short; `count` < 1 -> ValidationFailedError.
  - `topics(actor, emis_subject_id) -> dict[str, int]`: topic -> visible count.
  - `set_visibility(actor, question_id, visibility)`: owner only (else NotFoundError).
- Topics are NOT free text and NOT derived from the bank. `app.modules.notebooks.ports.
  question_bank.SubjectTopicCatalog.topics(emis_subject_id) -> tuple[str, ...] | None`
  (None = unknown EMIS subject) is the academic topic directory
  (`curriculum_topics`, filled from the EMIS thematic plan; a local subject with no
  EMIS id has no bank). `QuestionBankService(store, clock, catalog)`: an unknown
  subject -> NotFoundError; a topic outside the catalogue -> ValidationFailedError
  (compared after trimming); `topics()` lists EVERY catalogue topic with its visible
  count (0 included) so the UI can show where the bank is empty. The EMIS subject id
  is checked before any write or draw; `emis_subject_id` is an int, a non-int fails
  validation at the route (the route layer maps a UUID subject to its EMIS id and
  refuses subjects without one).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.modules.notebooks.application.question_bank import QuestionBankService
from app.modules.notebooks.domain.question_bank import question_key
from app.shared.actor import Actor, Role
from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.shared.contracts.teacher_ai import QuestionItem
from tests.factories import make_actor
from tests.notebooks.question_bank.fakes import (
    FakeQuestionBankStore,
    FakeSubjectTeaching,
    FakeTopicCatalog,
)

import pytest

PHYSICS, MATH = 101, 102
NOW = datetime(2026, 11, 27, tzinfo=UTC)


def items(n: int, prefix: str = "q") -> list[QuestionItem]:
    return [QuestionItem(f"{prefix}{i}?", f"a{i}") for i in range(n)]


@pytest.fixture
def rig() -> SimpleNamespace:
    store = FakeQuestionBankStore()
    clock = SimpleNamespace(now=lambda: NOW)
    catalog = FakeTopicCatalog(
        {PHYSICS: ("optics", "mechanics", "t"), MATH: ("optics",)}
    )
    return SimpleNamespace(
        store=store,
        service=QuestionBankService(store, clock, catalog, FakeSubjectTeaching()),
    )


async def test_save_records_owner_origin_subject_topic_and_difficulty(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)

    result = await rig.service.save_generated(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(2),
        difficulty="hard",
    )

    assert (len(result.saved), len(result.skipped)) == (2, 0)
    for q in result.saved:
        assert (q.owner_id, q.emis_subject_id, q.topic) == (
            teacher.user_id,
            PHYSICS,
            "optics",
        )
        assert (q.origin, q.visibility, q.difficulty) == ("ai", "teacher", "hard")
    assert len(rig.store.rows) == 2


async def test_teacher_written_questions_are_marked_teacher(
    rig: SimpleNamespace,
) -> None:
    result = await rig.service.save_generated(
        make_actor(Role.TEACHER),
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(1),
        origin="teacher",
        visibility="subject",
    )
    assert (result.saved[0].origin, result.saved[0].visibility) == (
        "teacher",
        "subject",
    )


async def test_duplicates_are_skipped_within_subject_and_topic(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)
    await rig.service.save_generated(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=[QuestionItem("What is light?", "a")],
    )

    again = await rig.service.save_generated(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=[QuestionItem("  what is LIGHT ?? ", "b"), QuestionItem("New?", "c")],
    )
    other_topic = await rig.service.save_generated(
        teacher,
        emis_subject_id=PHYSICS,
        topic="mechanics",
        questions=[QuestionItem("What is light?", "a")],
    )

    assert [q.question for q in again.saved] == ["New?"] and len(again.skipped) == 1
    assert len(other_topic.saved) == 1


def test_question_key_ignores_case_spaces_and_trailing_punctuation() -> None:
    assert question_key("What  is light?") == question_key(" what is LIGHT ")


@pytest.mark.parametrize("role", [Role.STUDENT, Role.COUNSELOR])
async def test_only_staff_use_the_bank(rig: SimpleNamespace, role: Role) -> None:
    actor = make_actor(role)
    with pytest.raises(ForbiddenError):
        await rig.service.save_generated(
            actor, emis_subject_id=PHYSICS, topic="t", questions=items(1)
        )
    with pytest.raises(ForbiddenError):
        await rig.service.draw(actor, emis_subject_id=PHYSICS, topic="t", count=1)


async def test_curriculum_topics_for_staff_only(rig: SimpleNamespace) -> None:
    topics = await rig.service.curriculum_topics(make_actor(Role.TEACHER), PHYSICS)
    assert topics == ("optics", "mechanics", "t")
    with pytest.raises(ForbiddenError):
        await rig.service.curriculum_topics(make_actor(Role.STUDENT), PHYSICS)


async def test_empty_topic_or_list_is_refused(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    with pytest.raises(ValidationFailedError):
        await rig.service.save_generated(
            teacher, emis_subject_id=PHYSICS, topic=" ", questions=items(1)
        )
    with pytest.raises(ValidationFailedError):
        await rig.service.save_generated(
            teacher, emis_subject_id=PHYSICS, topic="t", questions=[]
        )


async def test_draw_is_random_without_repeats_and_reproducible_by_seed(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)
    await rig.service.save_generated(
        teacher, emis_subject_id=PHYSICS, topic="optics", questions=items(30)
    )

    a = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=10, seed=7
    )
    b = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=10, seed=7
    )
    c = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=10, seed=8
    )

    assert [q.id for q in a] == [q.id for q in b] != [q.id for q in c]
    assert len({q.id for q in a}) == 10


async def test_draw_without_seed_still_never_repeats(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    await rig.service.save_generated(
        teacher, emis_subject_id=PHYSICS, topic="optics", questions=items(5)
    )

    drawn = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=5
    )

    assert len({q.id for q in drawn}) == 5


async def test_short_pool_returns_what_exists(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    await rig.service.save_generated(
        teacher, emis_subject_id=PHYSICS, topic="optics", questions=items(3)
    )

    assert (
        len(
            await rig.service.draw(
                teacher, emis_subject_id=PHYSICS, topic="optics", count=10
            )
        )
        == 3
    )
    with pytest.raises(ValidationFailedError):
        await rig.service.draw(
            teacher, emis_subject_id=PHYSICS, topic="optics", count=0
        )


async def test_draw_filters_by_difficulty_subject_and_topic(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)
    save = rig.service.save_generated
    await save(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(3, "e"),
        difficulty="easy",
    )
    await save(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(3, "h"),
        difficulty="hard",
    )
    await save(
        teacher, emis_subject_id=PHYSICS, topic="mechanics", questions=items(3, "m")
    )
    await save(teacher, emis_subject_id=MATH, topic="optics", questions=items(3, "x"))

    easy = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=9, difficulty="easy"
    )
    anyd = await rig.service.draw(
        teacher, emis_subject_id=PHYSICS, topic="optics", count=9
    )

    assert {q.difficulty for q in easy} == {"easy"} and len(easy) == 3
    assert len(anyd) == 6 and {q.emis_subject_id for q in anyd} == {PHYSICS}


async def test_visibility_private_by_default_shared_on_request(
    rig: SimpleNamespace,
) -> None:
    author, colleague = make_actor(Role.TEACHER), make_actor(Role.TEACHER)
    await rig.service.save_generated(
        author, emis_subject_id=PHYSICS, topic="optics", questions=items(2, "p")
    )
    shared = await rig.service.save_generated(
        author,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(2, "s"),
        visibility="subject",
    )

    seen = await rig.service.draw(
        colleague, emis_subject_id=PHYSICS, topic="optics", count=10
    )

    assert {q.id for q in seen} == {q.id for q in shared.saved}
    assert await rig.service.topics(colleague, PHYSICS) == {
        "optics": 2,
        "mechanics": 0,
        "t": 0,
    }
    assert await rig.service.topics(author, PHYSICS) == {
        "optics": 4,
        "mechanics": 0,
        "t": 0,
    }


async def test_only_the_owner_changes_visibility(rig: SimpleNamespace) -> None:
    author, colleague = make_actor(Role.TEACHER), make_actor(Role.TEACHER)
    saved = (
        await rig.service.save_generated(
            author, emis_subject_id=PHYSICS, topic="optics", questions=items(1)
        )
    ).saved[0]

    with pytest.raises(NotFoundError):
        await rig.service.set_visibility(colleague, saved.id, "subject")
    await rig.service.set_visibility(author, saved.id, "subject")

    assert rig.store.rows[saved.id].visibility == "subject"


async def test_unknown_emis_subject_or_topic_is_refused_before_any_write(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)

    with pytest.raises(NotFoundError):
        await rig.service.save_generated(
            teacher, emis_subject_id=999, topic="optics", questions=items(1)
        )
    with pytest.raises(NotFoundError):
        await rig.service.draw(teacher, emis_subject_id=999, topic="optics", count=1)
    with pytest.raises(NotFoundError):
        await rig.service.topics(teacher, 999)
    with pytest.raises(ValidationFailedError):
        await rig.service.save_generated(
            teacher, emis_subject_id=PHYSICS, topic="thermodynamics", questions=items(1)
        )
    with pytest.raises(ValidationFailedError):
        await rig.service.draw(
            teacher, emis_subject_id=PHYSICS, topic="thermodynamics", count=1
        )

    assert rig.store.rows == {}


async def test_topic_is_matched_after_trimming(rig: SimpleNamespace) -> None:
    result = await rig.service.save_generated(
        make_actor(Role.TEACHER),
        emis_subject_id=PHYSICS,
        topic="  optics ",
        questions=items(1),
    )

    assert result.saved[0].topic == "optics"


async def _saved(
    rig: SimpleNamespace, actor: Actor, n: int = 3, topic: Any = "optics", **kw: Any
) -> Any:
    result = await rig.service.save_generated(
        actor, emis_subject_id=PHYSICS, topic=topic, questions=items(n), **kw
    )
    return list(result.saved)


async def test_list_is_paginated_and_filters_by_topic(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    await _saved(rig, teacher, 3, "optics")
    await _saved(rig, teacher, 2, "mechanics", visibility="teacher")

    page, total = await rig.service.list_questions(
        teacher, emis_subject_id=PHYSICS, topic="optics", limit=2, offset=0
    )
    rest, _ = await rig.service.list_questions(
        teacher, emis_subject_id=PHYSICS, topic="optics", limit=2, offset=2
    )
    _, everything = await rig.service.list_questions(teacher, emis_subject_id=PHYSICS)

    assert (len(page), len(rest), total, everything) == (2, 1, 3, 5)
    assert {q.topic for q in page + rest} == {"optics"}


async def test_list_hides_other_teachers_private_questions(
    rig: SimpleNamespace,
) -> None:
    owner, other = make_actor(Role.TEACHER), make_actor(Role.TEACHER)
    await _saved(rig, owner, 2)

    _, total = await rig.service.list_questions(other, emis_subject_id=PHYSICS)

    assert total == 0


async def test_list_refuses_an_unknown_topic_and_students(rig: SimpleNamespace) -> None:
    with pytest.raises(ValidationFailedError):
        await rig.service.list_questions(
            make_actor(Role.TEACHER), emis_subject_id=PHYSICS, topic="nope"
        )
    with pytest.raises(ForbiddenError):
        await rig.service.list_questions(
            make_actor(Role.STUDENT), emis_subject_id=PHYSICS
        )


async def test_owner_edits_a_question(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    (q,) = await _saved(rig, teacher, 1)

    edited = await rig.service.edit(
        teacher,
        q.id,
        question="New text?",
        answer="42",
        options=["1", "42"],
        difficulty="hard",
    )

    assert (edited.question, edited.answer, edited.options) == (
        "New text?",
        "42",
        ("1", "42"),
    )
    assert rig.store.rows[q.id].difficulty == "hard"


async def test_edit_into_a_duplicate_conflicts(rig: SimpleNamespace) -> None:
    teacher = make_actor(Role.TEACHER)
    first, second = await _saved(rig, teacher, 2)

    with pytest.raises(ConflictError):
        await rig.service.edit(teacher, second.id, question=first.question, answer="x")


async def test_only_owner_or_admin_edits_and_deletes(rig: SimpleNamespace) -> None:
    owner, other, admin = (
        make_actor(Role.TEACHER),
        make_actor(Role.TEACHER),
        make_actor(Role.ADMIN),
    )
    first, second = await _saved(rig, owner, 2, visibility="subject")

    with pytest.raises(NotFoundError):
        await rig.service.edit(other, first.id, question="x?", answer="y")
    with pytest.raises(NotFoundError):
        await rig.service.delete(other, first.id)
    await rig.service.edit(admin, first.id, question="by admin?", answer="y")
    await rig.service.delete(admin, second.id)
    await rig.service.delete(owner, first.id)

    assert rig.store.rows == {}


async def test_save_inserts_all_new_questions_in_one_batch(
    rig: SimpleNamespace,
) -> None:
    teacher = make_actor(Role.TEACHER)
    await rig.service.save_generated(
        teacher,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=[
            QuestionItem("a?", "1"),
            QuestionItem("A?", "1"),
            QuestionItem("b?", "2"),
        ],
    )

    assert rig.store.batches == [2]


async def test_teacher_of_another_subject_is_refused_everywhere() -> None:
    outsider, physicist, admin = (
        make_actor(Role.TEACHER),
        make_actor(Role.TEACHER),
        make_actor(Role.ADMIN),
    )
    store = FakeQuestionBankStore()
    service = QuestionBankService(
        store,
        SimpleNamespace(now=lambda: NOW),
        FakeTopicCatalog({PHYSICS: ("optics",)}),
        FakeSubjectTeaching({physicist.user_id: {PHYSICS}, outsider.user_id: {MATH}}),
    )
    await service.save_generated(
        physicist,
        emis_subject_id=PHYSICS,
        topic="optics",
        questions=items(2),
        visibility="subject",
    )

    with pytest.raises(ForbiddenError):
        await service.save_generated(
            outsider, emis_subject_id=PHYSICS, topic="optics", questions=items(1)
        )
    with pytest.raises(ForbiddenError):
        await service.draw(outsider, emis_subject_id=PHYSICS, topic="optics", count=1)
    with pytest.raises(ForbiddenError):
        await service.topics(outsider, PHYSICS)
    with pytest.raises(ForbiddenError):
        await service.curriculum_topics(outsider, PHYSICS)
    with pytest.raises(ForbiddenError):
        await service.list_questions(outsider, emis_subject_id=PHYSICS)
    _, total = await service.list_questions(admin, emis_subject_id=PHYSICS)
    assert total == 2 and len(store.rows) == 2
