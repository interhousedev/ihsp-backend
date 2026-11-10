"""Teacher AI tools: validation, ownership of templates and the authorship caveat."""

import dataclasses
import io
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.teaching.tools import (
    PLAN_PREFIX,
    TeacherAi,
    TeacherInputError,
    TeacherTemplateNotFoundError,
)
from app.settings import Settings
from app.shared.actor import Role
from app.shared.ai_tasks import AiTask
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.contracts.teacher_ai import (
    CheckAuthorshipArgs,
    CheckWorkArgs,
    GenerateLessonPlanArgs,
    GenerateQuestionsArgs,
    RegisterPlanTemplateArgs,
)
from tests.fakes.notebooks.files import FakeNotebookFiles
from tests.fakes.notebooks.llm import ScriptedLlm

import pytest
from docx import Document

TEXT = "The student wrote a long enough answer about photosynthesis in leaves."


class Files(FakeNotebookFiles):
    """Adds the listing and the stored bytes the tools use."""

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """The owner's files."""
        return [f for f in self.files.values() if f.owner_id == owner_id][:limit]

    async def read_bytes(self, file_id: UUID) -> bytes:
        """The stored bytes."""
        return self.stored[file_id]


class Locale:
    """Every user reads English."""

    async def locale_of(self, user_id: Any) -> str:
        """English."""
        return "en"


def tools(settings: Settings) -> tuple[TeacherAi, Files, ScriptedLlm]:
    """The tools over fakes."""
    files, gateway = Files(), ScriptedLlm()
    return (
        TeacherAi(llm=NotebookLlm(gateway, settings), files=files, locale=Locale()),
        files,
        gateway,
    )


async def test_questions_follow_the_count(settings: Settings, make_actor: Any) -> None:
    """The fake model returns the asked number; the task is the teacher one."""
    ai, _, gateway = tools(settings)

    result = await ai.generate_questions(
        make_actor(Role.TEACHER), GenerateQuestionsArgs(topic="Cells", count=4)
    )

    assert len(result.questions) == 4
    assert gateway.json_requests[0]["tuning"].task == AiTask.TEACHER_QUESTIONS.value


async def test_a_bad_count_is_refused(settings: Settings, make_actor: Any) -> None:
    """Out-of-range counts never reach the model."""
    ai, _, gateway = tools(settings)

    with pytest.raises(TeacherInputError):
        await ai.generate_questions(
            make_actor(Role.TEACHER), GenerateQuestionsArgs(topic="Cells", count=99)
        )
    assert gateway.calls == 0


async def test_authorship_has_a_caveat_and_a_verdict(
    settings: Settings, make_actor: Any
) -> None:
    """The estimate is clamped and always carries the caveat."""
    ai, _, gateway = tools(settings)
    gateway.queue_json({"ai_likelihood": 7, "signals": ["Even rhythm"]})

    result = await ai.check_ai_authorship(
        make_actor(Role.TEACHER), CheckAuthorshipArgs(text=TEXT)
    )

    assert result.ai_likelihood == 1.0
    assert result.verdict == "likely_ai"
    assert "not proof" in result.caveat


async def test_the_score_is_clamped_to_the_maximum(
    settings: Settings, make_actor: Any
) -> None:
    """A model score above the maximum is cut."""
    ai, _, gateway = tools(settings)
    gateway.queue_json(
        {
            "summary": "Fine.",
            "score": 15,
            "strengths": [],
            "issues": [],
            "suggestions": [],
        }
    )

    result = await ai.check_work(
        make_actor(Role.TEACHER),
        CheckWorkArgs(assignment="Explain it", student_work=TEXT, max_score=10),
    )

    assert result.score == 10


async def test_a_template_is_listed_and_used_by_its_owner(
    settings: Settings, make_actor: Any
) -> None:
    """Register, list, then generate a plan that is stored as a file."""
    ai, files, _ = tools(settings)
    teacher = make_actor(Role.TEACHER)
    saved = await ai.register_plan_template(
        teacher, RegisterPlanTemplateArgs(name="Basic", template="# Goals\n# Stages")
    )

    listed = await ai.list_plan_templates(teacher)
    plan = await ai.generate_lesson_plan(
        teacher, GenerateLessonPlanArgs(topic="Cells", template_id=saved.id)
    )

    assert [t.id for t in listed] == [saved.id]
    assert plan.template_id == saved.id
    assert files.files[plan.id].name.startswith(PLAN_PREFIX)


async def test_another_teachers_template_is_not_found(
    settings: Settings, make_actor: Any
) -> None:
    """A template id of someone else behaves like a missing one."""
    ai, _, gateway = tools(settings)
    saved = await ai.register_plan_template(
        make_actor(Role.TEACHER), RegisterPlanTemplateArgs(name="Mine", template="# A")
    )

    with pytest.raises(TeacherTemplateNotFoundError):
        await ai.generate_lesson_plan(
            make_actor(Role.TEACHER),
            GenerateLessonPlanArgs(topic="Cells", template_id=saved.id),
        )
    assert gateway.calls == 0


async def _upload_docx(
    files: Files, owner_id: UUID, name: str = "layout.docx"
) -> FileRef:
    """A tiny template with a header, a heading and a body paragraph."""
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Lyceum header"
    document.add_heading("OLD TITLE", level=1)
    document.add_paragraph("old body")
    buffer = io.BytesIO()
    document.save(buffer)
    ref = await files.store_bytes(
        owner_id=owner_id,
        scope=FileScope.STAFF,
        purpose=FilePurpose.AI_UPLOAD,
        name=name,
        data=buffer.getvalue(),
    )
    return files.add_text(dataclasses.replace(ref, text_bytes=20), "OLD TITLE")


async def test_a_plan_from_a_docx_template_is_written_into_a_copy(
    settings: Settings, make_actor: Any
) -> None:
    """The result .docx keeps the header, drops the old body, has the headings."""
    ai, files, _ = tools(settings)
    teacher = make_actor(Role.TEACHER)
    upload = await _upload_docx(files, teacher.user_id)

    saved = await ai.register_plan_template(
        teacher, RegisterPlanTemplateArgs(name="Word", file_id=upload.id)
    )
    plan = await ai.generate_lesson_plan(
        teacher, GenerateLessonPlanArgs(topic="Cells", template_id=saved.id)
    )

    assert saved.source_file_id == upload.id
    assert plan.docx_file_id is not None
    assert files.files[plan.docx_file_id].name == "lesson-plan Lesson plan Cells.docx"
    result = Document(io.BytesIO(files.stored[plan.docx_file_id]))
    texts = [p.text for p in result.paragraphs]
    assert result.sections[0].header.paragraphs[0].text == "Lyceum header"
    assert "OLD TITLE" not in texts
    assert "Objectives" in texts


async def test_a_text_template_gives_no_docx(
    settings: Settings, make_actor: Any
) -> None:
    """Only a .docx template produces a Word file."""
    ai, _, _ = tools(settings)
    teacher = make_actor(Role.TEACHER)
    saved = await ai.register_plan_template(
        teacher, RegisterPlanTemplateArgs(name="Basic", template="# Goals")
    )

    plan = await ai.generate_lesson_plan(
        teacher, GenerateLessonPlanArgs(topic="Cells", template_id=saved.id)
    )

    assert plan.docx_file_id is None


async def test_another_teachers_docx_is_not_found(
    settings: Settings, make_actor: Any
) -> None:
    """A foreign file id behaves like a missing one."""
    ai, files, _ = tools(settings)
    owner, other = make_actor(Role.TEACHER), make_actor(Role.TEACHER)
    upload = await _upload_docx(files, owner.user_id)

    with pytest.raises(TeacherTemplateNotFoundError):
        await ai.register_plan_template(
            other, RegisterPlanTemplateArgs(name="Word", file_id=upload.id)
        )


async def test_a_template_needs_exactly_one_source(
    settings: Settings, make_actor: Any
) -> None:
    """Neither text nor file, or both, is refused."""
    ai, files, _ = tools(settings)
    teacher = make_actor(Role.TEACHER)
    upload = await _upload_docx(files, teacher.user_id)

    with pytest.raises(TeacherInputError):
        await ai.register_plan_template(teacher, RegisterPlanTemplateArgs(name="x"))
    with pytest.raises(TeacherInputError):
        await ai.register_plan_template(
            teacher,
            RegisterPlanTemplateArgs(name="x", template="t", file_id=upload.id),
        )
