"""Teacher AI tools: questions, handouts, work checks, AI authorship, lesson plans.

Implements `TeacherAiTools` for the teacher MCP server. Each call is one model call
of a named task (`TEACHER_*`); the gateway records usage and refuses revoked users.
Lesson plan templates and generated plans are the teacher's own text files in the
files module (`plan-template ...` and `lesson-plan ...`), so no table is needed.
"""

import re
from typing import Any, Literal
from uuid import UUID

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.teaching.plan_docx import plan_into_template
from app.modules.notebooks.domain.language import LANGUAGE_NAMES as LANGUAGE_CODES
from app.modules.notebooks.domain.language import (
    language_name,
    prompt_language,
    resolve_language,
)
from app.modules.notebooks.domain.teaching import schemas as sc
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.base_error import NotFoundError, ValidationFailedError
from app.shared.contracts.ai import AiInvalidOutputError
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope
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
    PlanTemplateResult,
    QuestionItem,
    RegisterPlanTemplateArgs,
)

from pydantic import BaseModel, ValidationError

_SOURCE_LINE = re.compile(r"<!-- docx:([0-9a-fA-F-]{36}) -->\n")
TEMPLATE_PREFIX = "plan-template "
PLAN_PREFIX = "lesson-plan "
MAX_QUESTIONS = 30
MAX_TEMPLATES = 50
MAX_TEMPLATE_CHARS = 8_000
LIST_SCAN = 500
AUTHORSHIP_CAVEATS = {
    "en": "This is an estimate, not proof. Detectors err; talk to the student.",
    "ru": (
        "Это оценка, а не доказательство. Детекторы ошибаются; "
        "поговорите с учеником."
    ),
    "uz": "Bu baho, isbot emas. Detektorlar adashadi; oʼquvchi bilan gaplashing.",
}
LIKELY_AI = 0.7
LIKELY_HUMAN = 0.35
MIN_TEXT_CHARS = 40
QUESTION_KINDS = {
    "multiple_choice": "multiple choice with 4 options",
    "short_answer": "short answer",
    "true_false": "true or false",
    "mixed": "a mix of multiple choice, short answer and true or false",
}
LENGTHS = {"short": "one page", "medium": "two pages", "long": "three to four pages"}
_NAME_CHARS = re.compile(r"[^\w\- ]+", re.UNICODE)


class TeacherTemplateNotFoundError(NotFoundError):
    """The template does not exist or is not the actor's own."""

    code = "notebooks/teacher-file-not-found"
    message_key = "notebooks-teacher-file-not-found"


class TeacherInputError(ValidationFailedError):
    """A tool argument is missing or out of range."""

    code = "notebooks/teacher-input-invalid"
    message_key = "notebooks-teacher-input-invalid"

    def __init__(self, detail: str) -> None:
        """Keep the detail for the user message and for support."""
        super().__init__(params={"detail": detail}, support_details=detail)


def _file_name(prefix: str, text: str) -> str:
    cleaned = " ".join(_NAME_CHARS.sub(" ", text).split())[:60].strip()
    return f"{prefix}{cleaned or 'untitled'}.md"


def _items(values: list[str], limit: int = 8, chars: int = 400) -> tuple[str, ...]:
    return tuple(v.strip()[:chars] for v in values if v.strip())[:limit]


def _required(value: str | None, what: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise TeacherInputError(f"{what} is empty")
    return text[:limit]


class TeacherAi:
    """The teacher tools on top of the notebooks LLM wrapper."""

    def __init__(
        self, *, llm: NotebookLlm, files: FilesApi, locale: LocaleResolver
    ) -> None:
        """Store the collaborators."""
        self.llm = llm
        self.files = files
        self.locale = locale

    async def _language(
        self, actor: Actor, requested: str | None, hint: str | None = None
    ) -> str:
        """As asked; else the language of the topic; else the teacher's locale."""
        if requested not in LANGUAGE_CODES:
            requested = prompt_language(hint) or requested
        return language_name(
            resolve_language(requested, await self.locale.locale_of(actor.user_id))
        )

    async def _ask(
        self,
        task: AiTask,
        system: str,
        message: str,
        name: str,
        model: type[BaseModel],
        max_tokens: int,
    ) -> Any:  # noqa: ANN401 - the validated output model
        done = await self.llm.json(
            task=task,
            system=system,
            messages=[{"role": "user", "content": message}],
            schema_name=name,
            schema=sc.schema_of(model),
            max_tokens=self.llm.max_tokens(task, max_tokens),
        )
        try:
            return model.model_validate(done.data)
        except ValidationError as exc:
            raise AiInvalidOutputError(support_details=name) from exc

    @staticmethod
    def _source(text: str | None) -> str:
        body = (text or "").strip()[: sc.SOURCE_MAX_CHARS]
        return f"{sc.tagged('source', body)}\n" if body else ""

    async def generate_questions(
        self, actor: Actor, args: GenerateQuestionsArgs
    ) -> GenerateQuestionsResult:
        """Questions with an answer key."""
        topic = _required(args.topic, "topic", 300)
        if not 1 <= args.count <= MAX_QUESTIONS:
            raise TeacherInputError(f"count must be 1 to {MAX_QUESTIONS}")
        kind = QUESTION_KINDS.get(args.question_type, QUESTION_KINDS["mixed"])
        message = (
            f"{sc.tagged('topic', topic)}\n{self._source(args.source_text)}"
            f"Write exactly {args.count} questions, {kind}. "
            f"Level or class: {(args.level or 'not given').strip()[:60]}. "
            f"Write in {await self._language(actor, args.language, topic)}."
        )
        out = await self._ask(
            AiTask.TEACHER_QUESTIONS,
            sc.QUESTIONS_SYSTEM,
            message,
            sc.QUESTIONS_SCHEMA,
            sc.QuestionsOut,
            sc.QUESTIONS_MAX_TOKENS,
        )
        questions = tuple(
            QuestionItem(
                question=q.question.strip(),
                answer=q.answer.strip(),
                options=_items(q.options),
                explanation=q.explanation.strip() or None,
            )
            for q in out.questions
            if q.question.strip() and q.answer.strip()
        )[: args.count]
        if not questions:
            raise AiInvalidOutputError(support_details="teacher questions: empty")
        return GenerateQuestionsResult(questions=questions)

    async def generate_handout(
        self, actor: Actor, args: GenerateHandoutArgs
    ) -> GenerateHandoutResult:
        """A handout in Markdown."""
        topic = _required(args.topic, "topic", 300)
        message = (
            f"{sc.tagged('topic', topic)}\n{self._source(args.source_text)}"
            f"Level or class: {(args.level or 'not given').strip()[:60]}. "
            f"Length: {LENGTHS.get(args.length, LENGTHS['medium'])}. "
            f"Write in {await self._language(actor, args.language, topic)}."
        )
        out = await self._ask(
            AiTask.TEACHER_HANDOUT,
            sc.HANDOUT_SYSTEM,
            message,
            sc.HANDOUT_SCHEMA,
            sc.HandoutOut,
            sc.HANDOUT_MAX_TOKENS,
        )
        markdown = out.markdown.strip()
        if not markdown:
            raise AiInvalidOutputError(support_details="teacher handout: empty")
        return GenerateHandoutResult(
            title=out.title.strip() or topic, markdown=markdown
        )

    async def check_work(self, actor: Actor, args: CheckWorkArgs) -> CheckWorkResult:
        """Feedback and a suggested score."""
        work = _required(args.student_work, "student_work", sc.WORK_MAX_CHARS)
        if len(work) < MIN_TEXT_CHARS:
            raise TeacherInputError(f"the work is shorter than {MIN_TEXT_CHARS}")
        assignment = _required(args.assignment, "assignment", 4_000)
        top = args.max_score
        if top is not None and top <= 0:
            raise TeacherInputError("max_score must be positive")
        message = (
            f"{sc.tagged('assignment', assignment)}\n"
            f"{sc.tagged('rubric', (args.rubric or '').strip()[:4_000])}\n"
            f"{sc.tagged('work', work)}\n"
            f"Maximum score: {top if top is not None else 10}. "
            f"Write in {await self._language(actor, args.language)}."
        )
        out = await self._ask(
            AiTask.TEACHER_WORK_CHECK,
            sc.WORK_SYSTEM,
            message,
            sc.WORK_SCHEMA,
            sc.WorkOut,
            sc.WORK_MAX_TOKENS,
        )
        return CheckWorkResult(
            summary=out.summary.strip(),
            score=None if top is None else round(min(max(out.score, 0.0), top), 2),
            max_score=top,
            strengths=_items(out.strengths),
            issues=_items(out.issues),
            suggestions=_items(out.suggestions),
        )

    async def check_ai_authorship(
        self, actor: Actor, args: CheckAuthorshipArgs
    ) -> CheckAuthorshipResult:
        """The likelihood that a text is AI-written; always with the caveat."""
        text = _required(args.text, "text", sc.WORK_MAX_CHARS)
        if len(text) < MIN_TEXT_CHARS:
            raise TeacherInputError(f"the text is shorter than {MIN_TEXT_CHARS}")
        locale = await self.locale.locale_of(actor.user_id)
        code = resolve_language(args.language, locale)
        message = (
            f"{sc.tagged('work', text)}\n"
            f"{sc.tagged('assignment', (args.context or '').strip()[:2_000])}\n"
            f"Write signals in {language_name(code)}."
        )
        out = await self._ask(
            AiTask.TEACHER_AI_CHECK,
            sc.AI_CHECK_SYSTEM,
            message,
            sc.AI_CHECK_SCHEMA,
            sc.AiCheckOut,
            sc.AI_CHECK_MAX_TOKENS,
        )
        likelihood = round(min(max(out.ai_likelihood, 0.0), 1.0), 2)
        verdict: Literal["likely_human", "uncertain", "likely_ai"] = (
            "likely_ai"
            if likelihood >= LIKELY_AI
            else "likely_human" if likelihood < LIKELY_HUMAN else "uncertain"
        )
        return CheckAuthorshipResult(
            verdict=verdict,
            ai_likelihood=likelihood,
            signals=_items(out.signals),
            caveat=AUTHORSHIP_CAVEATS[code],
        )

    async def _templates(self, actor: Actor) -> list[FileRef]:
        owned = await self.files.list_owned(actor.user_id, limit=LIST_SCAN)
        return [f for f in owned if f.name.startswith(TEMPLATE_PREFIX)][:MAX_TEMPLATES]

    @staticmethod
    def _template_result(ref: FileRef) -> PlanTemplateResult:
        name = ref.name.removeprefix(TEMPLATE_PREFIX).removesuffix(".md")
        return PlanTemplateResult(id=ref.id, name=name)

    async def list_plan_templates(self, actor: Actor) -> tuple[PlanTemplateResult, ...]:
        """The teacher's templates, newest first."""
        return tuple(self._template_result(f) for f in await self._templates(actor))

    async def register_plan_template(
        self, actor: Actor, args: RegisterPlanTemplateArgs
    ) -> PlanTemplateResult:
        """Store a template (pasted text or an uploaded .docx) as a file."""
        name = _required(args.name, "name", 60)
        if (args.file_id is None) == (not (args.template or "").strip()):
            raise TeacherInputError("give either template or file_id")
        if args.file_id is not None:
            template = await self._docx_text(actor, args.file_id)
            stored = f"<!-- docx:{args.file_id} -->\n{template}"
        else:
            template = _required(args.template, "template", MAX_TEMPLATE_CHARS)
            stored = template
        if len(await self._templates(actor)) >= MAX_TEMPLATES:
            raise TeacherInputError(f"at most {MAX_TEMPLATES} templates")
        ref = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.AI_UPLOAD,
            name=_file_name(TEMPLATE_PREFIX, name),
            data=stored.encode(),
        )
        return PlanTemplateResult(
            id=ref.id,
            name=name,
            description=(args.description or None),
            source_file_id=args.file_id,
        )

    async def _template_text(
        self, actor: Actor, template_id: UUID
    ) -> tuple[str, UUID | None]:
        """The template text and the .docx it came from, if any."""
        ref = await self.files.get(template_id)
        if (
            ref is None
            or ref.owner_id != actor.user_id
            or ref.status == "deleted"
            or not ref.name.startswith(TEMPLATE_PREFIX)
        ):
            raise TeacherTemplateNotFoundError()
        text = (await self.files.read_bytes(template_id)).decode(errors="replace")
        found = _SOURCE_LINE.match(text)
        if found is None:
            return text[:MAX_TEMPLATE_CHARS], None
        return text[found.end() :][:MAX_TEMPLATE_CHARS], UUID(found.group(1))

    async def _docx_text(self, actor: Actor, file_id: UUID) -> str:
        """The text of the teacher's own uploaded .docx."""
        ref = await self.files.get(file_id)
        if ref is None or ref.owner_id != actor.user_id or ref.status == "deleted":
            raise TeacherTemplateNotFoundError()
        if not ref.name.lower().endswith(".docx"):
            raise TeacherInputError("file_id must be a .docx file")
        full = await self.files.read_text_with_pages(file_id)
        return _required(full.text, "the .docx text", MAX_TEMPLATE_CHARS)

    async def generate_lesson_plan(
        self, actor: Actor, args: GenerateLessonPlanArgs
    ) -> GenerateLessonPlanResult:
        """A lesson plan in Markdown, kept as the teacher's file."""
        topic = _required(args.topic, "topic", 300)
        if not 5 <= args.duration_minutes <= 240:
            raise TeacherInputError("duration_minutes must be 5 to 240")
        template, source_id = "", None
        if args.template_id:
            text, source_id = await self._template_text(actor, args.template_id)
            template = sc.tagged("template", text)
        message = (
            f"{sc.tagged('topic', topic)}\n{template}\n"
            f"{sc.tagged('source', (args.notes or '').strip()[:4_000])}\n"
            f"Lesson duration: {args.duration_minutes} minutes. "
            f"Write in {await self._language(actor, args.language)}."
        )
        out = await self._ask(
            AiTask.TEACHER_LESSON_PLAN,
            sc.PLAN_SYSTEM,
            message,
            sc.PLAN_SCHEMA,
            sc.PlanOut,
            sc.PLAN_MAX_TOKENS,
        )
        markdown = out.markdown.strip()
        if not markdown:
            raise AiInvalidOutputError(support_details="teacher plan: empty")
        title = out.title.strip() or topic
        ref = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.AI_UPLOAD,
            name=_file_name(PLAN_PREFIX, title),
            data=markdown.encode(),
        )
        docx_id = await self._plan_docx(actor, source_id, title, markdown)
        return GenerateLessonPlanResult(
            id=ref.id,
            title=title,
            markdown=markdown,
            template_id=args.template_id,
            docx_file_id=docx_id,
        )

    async def _plan_docx(
        self, actor: Actor, source_id: UUID | None, title: str, markdown: str
    ) -> UUID | None:
        """The plan written into a copy of the template .docx, if it has one."""
        if source_id is None:
            return None
        source = await self.files.get(source_id)
        if source is None or source.owner_id != actor.user_id:
            return None
        if source.status == "deleted":
            return None
        data = plan_into_template(await self.files.read_bytes(source_id), markdown)
        ref = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.AI_UPLOAD,
            name=_file_name(PLAN_PREFIX, title).removesuffix(".md") + ".docx",
            data=data,
        )
        return ref.id
