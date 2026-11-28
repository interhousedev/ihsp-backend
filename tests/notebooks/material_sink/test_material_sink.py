"""Every teacher AI output lands in the subject notebook (spec 3.2a, "Material sink").

Questions, handouts, lesson plans, work checks and media become TEXT sources with their
full text, in the group notebook when a group is given, else the teacher's subject
notebook, so the notebook assistant can answer from them. Media is stored as its
script with the segment timecodes (never transcribed after the build), so a citation
can point to a moment of the video. The authorship check is not stored: it judges a
student's text, not a teaching material.

Review fixes (round 3):
- Destination is authorized: `TeachingScope.can_teach(actor, subject_id, group_id)
  -> bool` (`app.shared.contracts.teaching_scope`; real one wraps `TeachingDirectory`
  like `staff_subject_materials`: current assignment, subgroup, admin passes) gates
  `MaterialSink.store` AND runs in `SinkingTeacherAi` BEFORE the model call, so a
  forbidden destination spends nothing and writes nothing. `MaterialSink(notebooks,
  sources, scope)`.
- Work checks are `sensitive`: origin `{"teacher_ai": "work_check", "sensitive":
  True}` and `ref["sensitive"] = True`. Retrieval must hand such sources only to the
  owner's own notebook chat and mark every task that read one as sensitive for
  tracing (propagated from the source, not from the task name).
- Dedupe key = sha256 over the body AND the media identity (`media_file_id` and every
  segment start/end): two different videos with the same script are two sources.
- `kind` also accepts "artifact": a finished Studio artifact (quiz, slides, mind map,
  ...) is sunk by the artifact completion path with its text rendering.
- `citation_for(source_ref, body_md, passage) -> MediaCitation | None`
  (`media_file_id`, `start_ms`): maps the `[mm:ss]` line containing the cited passage
  to the segment; the web link plays that moment through `media_grants`.

The implementation must provide:
- `app.shared.contracts.material_sink` (so `media` can use it without importing
  `notebooks`): `Material` frozen dataclass (segments typed by a structural `TimedText`
  protocol: id, speaker, text, start_ms, end_ms) and the `MaterialSink` protocol
  `store(actor, material)`. `Material` fields: kind
  "questions"|"handout"|"lesson_plan"|"work_check"|"media"|"artifact", title, body_md,
  subject_id, group_id|None, segments = (), media_file_id|None.
  `app.modules.notebooks.domain.material_text`: `media_text(title, segments) -> str` one
  line per segment "[mm:ss] text";
  `questions_text(topic, questions)`, `work_check_text(result)` -> markdown with every
  field (answers, explanations, score, strengths, issues, suggestions).
- `app.modules.notebooks.ports.material_sink`: `NotebookDirectory.subject_notebook(
  owner_id, subject_id, group_id) -> UUID` and `SourceWriter.add_text(*, notebook_id,
  owner_id, title, body_md, ref, ref_key, origin) -> Source` (idempotent on
  (notebook_id, ref_key)).
- `app.modules.notebooks.application.material_sink.MaterialSink(notebooks, sources,
  scope)
  .store(actor, material) -> Source`: `ref_key` = `teacher_ai:<kind>:<sha256 of
  body_md + media identity>` (see below); `origin` = `{"teacher_ai": kind}`; media `ref`
  = `{"media_file_id",
  "segments": [{"start_ms","end_ms"}]}`. Students -> ForbiddenError.
- `app.modules.notebooks.application.teaching.sinking.SinkingTeacherAi(inner, sink)`
  implements `TeacherAiTools`: runs `inner`, then stores the output; the args
  `GenerateQuestionsArgs`, `GenerateHandoutArgs`, `CheckWorkArgs`,
  `GenerateLessonPlanArgs` gain `subject_id: UUID | None = None` and
  `group_id: UUID | None = None`; no `subject_id` -> the result is returned and
  nothing is stored. `check_ai_authorship`, template calls are passed through
  without storing.
"""

from types import SimpleNamespace
from typing import Any

from app.modules.media.domain.narration import Segment
from app.modules.notebooks.application.material_sink import MaterialSink
from app.modules.notebooks.application.teaching.sinking import SinkingTeacherAi
from app.modules.notebooks.domain.material_text import citation_for, media_text
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.material_sink import Material
from app.shared.contracts.teacher_ai import (
    CheckAuthorshipArgs,
    CheckAuthorshipResult,
    CheckWorkArgs,
    CheckWorkResult,
    GenerateHandoutArgs,
    GenerateHandoutResult,
    GenerateLessonPlanArgs,
    GenerateLessonPlanResult,
    GenerateQuestionsArgs,
    GenerateQuestionsResult,
    QuestionItem,
)
from app.shared.ids import new_id
from tests.factories import make_actor
from tests.notebooks.material_sink.fakes import FakeNotebooks, FakeScope, FakeSources

import pytest

SUBJECT = new_id()
SEGMENTS = (
    Segment("s1", "teacher", "Light bends at a boundary", 0, 12_000),
    Segment("s2", "teacher", "Snell's law", 12_000, 134_000),
)


class Inner:
    """The real tools' outputs, canned."""

    calls = 0

    async def generate_questions(self, actor: Actor, args: Any) -> Any:
        self.calls += 1
        return GenerateQuestionsResult(
            (QuestionItem("2+2?", "4", options=("3", "4"), explanation="sum"),)
        )

    async def generate_handout(self, actor: Actor, args: Any) -> Any:
        self.calls += 1
        return GenerateHandoutResult("Optics", "# Optics\nLight bends.")

    async def check_work(self, actor: Actor, args: Any) -> Any:
        self.calls += 1
        return CheckWorkResult(
            "ok", 4.0, 5.0, strengths=("clear",), issues=("no units",)
        )

    async def check_ai_authorship(self, actor: Actor, args: Any) -> Any:
        return CheckAuthorshipResult("uncertain", 0.4, ("flat",), "an estimate")

    async def generate_lesson_plan(self, actor: Actor, args: Any) -> Any:
        self.calls += 1
        return GenerateLessonPlanResult(new_id(), "Plan", "# Plan\n1. Goal", None)


@pytest.fixture
def rig() -> SimpleNamespace:
    notebooks, sources, scope, inner = (
        FakeNotebooks(),
        FakeSources(),
        FakeScope(),
        Inner(),
    )
    sink = MaterialSink(notebooks, sources, scope)
    return SimpleNamespace(
        notebooks=notebooks,
        sources=sources,
        sink=sink,
        scope=scope,
        inner=inner,
        tools=SinkingTeacherAi(inner, sink),
    )


def teacher_of(rig: SimpleNamespace, group: Any = None) -> Any:
    """A teacher who teaches SUBJECT (and `group`) now."""
    teacher = make_actor(Role.TEACHER)
    rig.scope.allow(teacher, SUBJECT, None)
    if group is not None:
        rig.scope.allow(teacher, SUBJECT, group)
    return teacher


def test_media_text_carries_a_timecode_per_segment() -> None:
    text = media_text("Optics video", SEGMENTS)

    assert "Optics video" in text
    assert "[00:00] Light bends at a boundary" in text
    assert "[00:12] Snell's law" in text


async def test_questions_are_stored_with_answers_and_explanations(
    rig: SimpleNamespace,
) -> None:
    teacher = teacher_of(rig)

    await rig.tools.generate_questions(
        teacher, GenerateQuestionsArgs("optics", 1, subject_id=SUBJECT)
    )

    (src,) = rig.sources.rows
    assert src.owner_id == teacher.user_id and src.origin == {"teacher_ai": "questions"}
    for part in ("2+2?", "3", "4", "sum"):
        assert part in src.body_md


async def test_subject_scope_without_group_group_scope_with_one(
    rig: SimpleNamespace,
) -> None:
    group = new_id()
    teacher = teacher_of(rig, group)

    await rig.tools.generate_handout(
        teacher, GenerateHandoutArgs("optics", subject_id=SUBJECT)
    )
    await rig.tools.generate_handout(
        teacher, GenerateHandoutArgs("optics", subject_id=SUBJECT, group_id=group)
    )

    assert set(rig.notebooks.notebooks) == {
        (teacher.user_id, SUBJECT, None),
        (teacher.user_id, SUBJECT, group),
    }
    assert len({s.notebook_id for s in rig.sources.rows}) == 2
    assert all("Light bends." in s.body_md for s in rig.sources.rows)


async def test_plan_and_work_check_are_stored_in_full(rig: SimpleNamespace) -> None:
    teacher = teacher_of(rig)

    await rig.tools.generate_lesson_plan(
        teacher, GenerateLessonPlanArgs("optics", subject_id=SUBJECT)
    )
    await rig.tools.check_work(
        teacher, CheckWorkArgs("essay", "text", max_score=5, subject_id=SUBJECT)
    )

    plan, check = rig.sources.rows
    assert "1. Goal" in plan.body_md and plan.origin == {"teacher_ai": "lesson_plan"}
    assert check.origin == {"teacher_ai": "work_check", "sensitive": True}
    assert check.ref["sensitive"] is True
    for part in ("4", "5", "clear", "no units"):
        assert part in check.body_md


async def test_authorship_check_is_not_stored(rig: SimpleNamespace) -> None:
    result = await rig.tools.check_ai_authorship(
        make_actor(Role.TEACHER), CheckAuthorshipArgs("some text")
    )

    assert result.verdict == "uncertain" and rig.sources.rows == []


async def test_without_a_subject_the_result_is_returned_and_nothing_stored(
    rig: SimpleNamespace,
) -> None:
    result = await rig.tools.generate_handout(
        make_actor(Role.TEACHER), GenerateHandoutArgs("optics")
    )

    assert result.title == "Optics" and rig.sources.rows == []


async def test_media_is_stored_as_script_with_timecodes_and_file_link(
    rig: SimpleNamespace,
) -> None:
    teacher, file_id = teacher_of(rig), new_id()
    body = media_text("Optics video", SEGMENTS)

    src = await rig.sink.store(
        teacher,
        Material("media", "Optics video", body, SUBJECT, None, SEGMENTS, file_id),
    )

    assert "[02:14]" not in src.body_md and "[00:12] Snell's law" in src.body_md
    assert src.ref["media_file_id"] == file_id
    assert src.ref["segments"] == [
        {"start_ms": 0, "end_ms": 12_000},
        {"start_ms": 12_000, "end_ms": 134_000},
    ]


async def test_storing_the_same_material_twice_keeps_one_source(
    rig: SimpleNamespace,
) -> None:
    teacher = teacher_of(rig)
    args = GenerateHandoutArgs("optics", subject_id=SUBJECT)

    await rig.tools.generate_handout(teacher, args)
    await rig.tools.generate_handout(teacher, args)

    assert len(rig.sources.rows) == 1


async def test_students_cannot_store_materials(rig: SimpleNamespace) -> None:
    student = make_actor(Role.STUDENT)
    rig.scope.allow(student, SUBJECT, None)
    with pytest.raises(ForbiddenError):
        await rig.sink.store(student, Material("handout", "t", "body", SUBJECT, None))


async def test_unrelated_subject_group_or_expired_assignment_is_refused_before_the_model(  # noqa: E501
    rig: SimpleNamespace,
) -> None:
    teacher, group = (
        teacher_of(rig),
        new_id(),
    )  # teaches SUBJECT as a whole, not `group`

    with pytest.raises(ForbiddenError):
        await rig.tools.generate_handout(
            teacher, GenerateHandoutArgs("optics", subject_id=new_id())
        )
    with pytest.raises(ForbiddenError):
        await rig.tools.generate_questions(
            teacher,
            GenerateQuestionsArgs("optics", 1, subject_id=SUBJECT, group_id=group),
        )
    with pytest.raises(ForbiddenError):  # the direct store path is gated too
        await rig.sink.store(teacher, Material("handout", "t", "b", new_id(), None))

    assert rig.inner.calls == 0  # forbidden destination: no model spend
    assert rig.sources.rows == [] and rig.notebooks.notebooks == {}


async def test_admin_may_store_into_any_subject(rig: SimpleNamespace) -> None:
    await rig.sink.store(
        make_actor(Role.ADMIN), Material("handout", "t", "body", new_id(), None)
    )

    assert len(rig.sources.rows) == 1


@pytest.mark.parametrize(
    "kind", ["questions", "handout", "lesson_plan", "work_check", "media", "artifact"]
)
async def test_every_kind_is_stored_with_its_origin(
    rig: SimpleNamespace, kind: Any
) -> None:
    teacher = teacher_of(rig)

    src = await rig.sink.store(
        teacher, Material(kind, "t", f"body {kind}", SUBJECT, None)
    )

    assert src.origin["teacher_ai"] == kind


async def test_two_videos_with_the_same_script_are_two_sources(
    rig: SimpleNamespace,
) -> None:
    teacher, body = teacher_of(rig), media_text("Optics video", SEGMENTS)

    first = await rig.sink.store(
        teacher, Material("media", "v", body, SUBJECT, None, SEGMENTS, new_id())
    )
    second = await rig.sink.store(
        teacher, Material("media", "v", body, SUBJECT, None, SEGMENTS, new_id())
    )

    assert first.id != second.id and len(rig.sources.rows) == 2


async def test_same_script_with_different_timing_is_a_new_source(
    rig: SimpleNamespace,
) -> None:
    teacher, file_id, body = teacher_of(rig), new_id(), media_text("v", SEGMENTS)
    slower = (SEGMENTS[0], Segment("s2", "teacher", "Snell's law", 12_000, 140_000))

    await rig.sink.store(
        teacher, Material("media", "v", body, SUBJECT, None, SEGMENTS, file_id)
    )
    await rig.sink.store(
        teacher, Material("media", "v", body, SUBJECT, None, slower, file_id)
    )
    await rig.sink.store(
        teacher, Material("media", "v", body, SUBJECT, None, SEGMENTS, file_id)
    )

    assert len(rig.sources.rows) == 2  # the exact repeat is still deduplicated


async def test_a_citation_resolves_to_the_media_file_and_moment(
    rig: SimpleNamespace,
) -> None:
    teacher, file_id = teacher_of(rig), new_id()
    body = media_text("Optics video", SEGMENTS)
    src = await rig.sink.store(
        teacher,
        Material("media", "Optics video", body, SUBJECT, None, SEGMENTS, file_id),
    )

    cited = citation_for(src.ref, src.body_md, "Snell's law")

    assert (cited.media_file_id, cited.start_ms) == (file_id, 12_000)
    assert citation_for(src.ref, src.body_md, "never said") is None
