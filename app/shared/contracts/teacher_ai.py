"""What the AI tools of the teacher MCP server need (implemented by another module).

Each method takes the teacher as an `Actor` from the guard and a frozen dataclass of
arguments, and returns a frozen dataclass of plain fields. The implementation owns
the model call, its AI task, limits and the usage ledger.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

QuestionType = Literal["multiple_choice", "short_answer", "true_false", "mixed"]
HandoutLength = Literal["short", "medium", "long"]
AuthorshipVerdict = Literal["likely_human", "uncertain", "likely_ai"]


@dataclass(frozen=True, slots=True)
class GenerateQuestionsArgs:
    """Questions for a topic or a pasted source text."""

    topic: str
    count: int = 10
    question_type: QuestionType = "mixed"
    level: str | None = None
    language: str | None = None
    source_text: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionItem:
    """One generated question."""

    question: str
    answer: str
    options: tuple[str, ...] = ()
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class GenerateQuestionsResult:
    """The generated questions."""

    questions: tuple[QuestionItem, ...]


@dataclass(frozen=True, slots=True)
class GenerateHandoutArgs:
    """A printable handout on a topic."""

    topic: str
    level: str | None = None
    language: str | None = None
    length: HandoutLength = "medium"
    source_text: str | None = None


@dataclass(frozen=True, slots=True)
class GenerateHandoutResult:
    """The handout as Markdown."""

    title: str
    markdown: str


@dataclass(frozen=True, slots=True)
class CheckWorkArgs:
    """A student's work checked against the assignment."""

    assignment: str
    student_work: str
    rubric: str | None = None
    max_score: float | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class CheckWorkResult:
    """The verdict on a student's work."""

    summary: str
    score: float | None
    max_score: float | None
    strengths: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckAuthorshipArgs:
    """A text to judge for machine authorship."""

    text: str
    context: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class CheckAuthorshipResult:
    """The estimate; a hint for the teacher, never proof."""

    verdict: AuthorshipVerdict
    ai_likelihood: float
    signals: tuple[str, ...] = ()
    caveat: str = ""


@dataclass(frozen=True, slots=True)
class RegisterPlanTemplateArgs:
    """A lesson plan template of the teacher."""

    name: str
    template: str | None = None
    description: str | None = None
    file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PlanTemplateResult:
    """A stored lesson plan template."""

    id: UUID
    name: str
    description: str | None = None
    source_file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GenerateLessonPlanArgs:
    """A lesson plan for a topic, optionally for a lesson and in a template."""

    topic: str
    lesson_id: UUID | None = None
    template_id: UUID | None = None
    duration_minutes: int = 45
    language: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class GenerateLessonPlanResult:
    """The plan as Markdown."""

    id: UUID
    title: str
    markdown: str
    template_id: UUID | None = None
    docx_file_id: UUID | None = None


class TeacherAiTools(Protocol):
    """Model-backed helpers for teachers."""

    async def generate_questions(
        self, actor: Actor, args: GenerateQuestionsArgs
    ) -> GenerateQuestionsResult:
        """Generate questions with answers."""
        ...

    async def generate_handout(
        self, actor: Actor, args: GenerateHandoutArgs
    ) -> GenerateHandoutResult:
        """Generate a handout."""
        ...

    async def check_work(self, actor: Actor, args: CheckWorkArgs) -> CheckWorkResult:
        """Check a student's work."""
        ...

    async def check_ai_authorship(
        self, actor: Actor, args: CheckAuthorshipArgs
    ) -> CheckAuthorshipResult:
        """Estimate whether a text was written by a model."""
        ...

    async def list_plan_templates(self, actor: Actor) -> tuple[PlanTemplateResult, ...]:
        """The teacher's lesson plan templates."""
        ...

    async def register_plan_template(
        self, actor: Actor, args: RegisterPlanTemplateArgs
    ) -> PlanTemplateResult:
        """Store a lesson plan template."""
        ...

    async def generate_lesson_plan(
        self, actor: Actor, args: GenerateLessonPlanArgs
    ) -> GenerateLessonPlanResult:
        """Generate a lesson plan."""
        ...
