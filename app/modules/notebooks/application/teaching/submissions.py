"""Teacher AI tools that read the checked submission server-side."""

from dataclasses import replace

from app.shared.actor import Actor
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
    SubmissionReader,
    TeacherAiTools,
)


class SubmissionResolvingTeacherAi:
    """Fills the checks from a `submission_id` before the inner tools run."""

    def __init__(self, inner: TeacherAiTools, reader: SubmissionReader) -> None:
        """Wrap the tools with the actor-scoped reader."""
        self.inner = inner
        self.reader = reader

    async def check_work(self, actor: Actor, args: CheckWorkArgs) -> CheckWorkResult:
        """Check the submission's text; its subject and group are the destination."""
        if args.submission_id is not None:
            work = await self.reader.read(actor, args.submission_id)
            args = replace(
                args,
                assignment=work.assignment,
                student_work=work.student_work,
                subject_id=args.subject_id or work.subject_id,
                group_id=args.group_id or work.group_id,
            )
        return await self.inner.check_work(actor, args)

    async def check_ai_authorship(
        self, actor: Actor, args: CheckAuthorshipArgs
    ) -> CheckAuthorshipResult:
        """Estimate authorship of the submission's text."""
        if args.submission_id is not None:
            work = await self.reader.read(actor, args.submission_id)
            args = replace(args, text=work.student_work)
        return await self.inner.check_ai_authorship(actor, args)

    async def generate_questions(
        self, actor: Actor, args: GenerateQuestionsArgs
    ) -> GenerateQuestionsResult:
        """Pass through."""
        return await self.inner.generate_questions(actor, args)

    async def generate_handout(
        self, actor: Actor, args: GenerateHandoutArgs
    ) -> GenerateHandoutResult:
        """Pass through."""
        return await self.inner.generate_handout(actor, args)

    async def list_plan_templates(self, actor: Actor) -> tuple[PlanTemplateResult, ...]:
        """Pass through."""
        return await self.inner.list_plan_templates(actor)

    async def register_plan_template(
        self, actor: Actor, args: RegisterPlanTemplateArgs
    ) -> PlanTemplateResult:
        """Pass through."""
        return await self.inner.register_plan_template(actor, args)

    async def generate_lesson_plan(
        self, actor: Actor, args: GenerateLessonPlanArgs
    ) -> GenerateLessonPlanResult:
        """Pass through."""
        return await self.inner.generate_lesson_plan(actor, args)
