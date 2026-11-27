"""Teacher AI tools that also put their output into the subject notebook."""

from app.modules.notebooks.application.material_sink import MaterialSink
from app.modules.notebooks.domain.material_text import (
    questions_text,
    work_check_text,
)
from app.shared.actor import Actor
from app.shared.contracts.material_sink import Material, MaterialKind
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
    RegisterPlanTemplateArgs,
    TeacherAiTools,
)

_TITLE_MAX = 120


class SinkingTeacherAi:
    """Runs the inner tools, then stores the full output when a subject is given."""

    def __init__(self, inner: TeacherAiTools, sink: MaterialSink) -> None:
        """Wrap the tools with the sink."""
        self.inner = inner
        self.sink = sink

    async def _gate(
        self,
        actor: Actor,
        args: (
            GenerateQuestionsArgs
            | GenerateHandoutArgs
            | CheckWorkArgs
            | GenerateLessonPlanArgs
        ),
    ) -> bool:
        """Authorize the destination before any model spend."""
        if args.subject_id is None:
            return False
        await self.sink.authorize(actor, args.subject_id, args.group_id)
        return True

    async def _store(
        self,
        actor: Actor,
        args: (
            GenerateQuestionsArgs
            | GenerateHandoutArgs
            | CheckWorkArgs
            | GenerateLessonPlanArgs
        ),
        kind: MaterialKind,
        title: str,
        body: str,
    ) -> None:
        assert args.subject_id is not None
        await self.sink.store(
            actor,
            Material(kind, title[:_TITLE_MAX], body, args.subject_id, args.group_id),
        )

    async def generate_questions(
        self, actor: Actor, args: GenerateQuestionsArgs
    ) -> GenerateQuestionsResult:
        """Generate questions and store them with answers and explanations."""
        sink = await self._gate(actor, args)
        result = await self.inner.generate_questions(actor, args)
        if sink:
            body = questions_text(args.topic, result.questions)
            await self._store(actor, args, "questions", args.topic, body)
        return result

    async def generate_handout(
        self, actor: Actor, args: GenerateHandoutArgs
    ) -> GenerateHandoutResult:
        """Generate a handout and store its Markdown."""
        sink = await self._gate(actor, args)
        result = await self.inner.generate_handout(actor, args)
        if sink:
            await self._store(actor, args, "handout", result.title, result.markdown)
        return result

    async def check_work(self, actor: Actor, args: CheckWorkArgs) -> CheckWorkResult:
        """Check a work and store the whole verdict (sensitive)."""
        sink = await self._gate(actor, args)
        result = await self.inner.check_work(actor, args)
        if sink:
            title = f"Work check: {args.assignment}"
            await self._store(actor, args, "work_check", title, work_check_text(result))
        return result

    async def check_ai_authorship(
        self, actor: Actor, args: CheckAuthorshipArgs
    ) -> CheckAuthorshipResult:
        """Judges a student's text; never stored."""
        return await self.inner.check_ai_authorship(actor, args)

    async def list_plan_templates(self, actor: Actor) -> tuple[PlanTemplateResult, ...]:
        """Passed through."""
        return await self.inner.list_plan_templates(actor)

    async def register_plan_template(
        self, actor: Actor, args: RegisterPlanTemplateArgs
    ) -> PlanTemplateResult:
        """Passed through."""
        return await self.inner.register_plan_template(actor, args)

    async def generate_lesson_plan(
        self, actor: Actor, args: GenerateLessonPlanArgs
    ) -> GenerateLessonPlanResult:
        """Generate a lesson plan and store its Markdown."""
        sink = await self._gate(actor, args)
        result = await self.inner.generate_lesson_plan(actor, args)
        if sink:
            await self._store(actor, args, "lesson_plan", result.title, result.markdown)
        return result
