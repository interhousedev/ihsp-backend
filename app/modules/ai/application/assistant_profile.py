"""Per-assistant configuration: role, model profile, token limits and tool rounds."""

from dataclasses import dataclass

from app.modules.ai.domain.assistant import ASSISTANT_ROLE, Assistant
from app.modules.ai.domain.chat import ChatTier
from app.modules.ai.domain.errors import WrongAssistantError
from app.settings import LimitsSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.ai_tasks import AiTask, ModelProfile
from app.shared.limits import ActorLimits


@dataclass(frozen=True, slots=True)
class AssistantProfile:
    """What differs between the student, Administration and course author assistants.

    `role` is None for the course author assistant: it is allowed per course (the
    ``edit`` permission), not by a global role. `course_pool` marks the budget pool
    of course staff (`ai:lms`), shared with the course workspace of notebooks.
    """

    assistant: Assistant
    role: Role | None
    llm: ModelProfile  # the model and its parameters (`AI__TASKS__...`)
    session_tokens: int | None  # None: no cap (Administration)
    daily_tokens: int | None
    max_tool_steps: int
    course_pool: bool = False

    @property
    def model(self) -> str:
        """The model id the assistant's chats are stored with."""
        return self.llm.model

    @property
    def weight(self) -> int:
        """How many budget tokens one model token counts for."""
        return self.llm.budget_weight


def effective_tier(assistant: Assistant, tier: ChatTier | None) -> ChatTier:
    """Return the tier a chat really gets: only the student assistant has `smart`."""
    if assistant is Assistant.STUDENT and tier is not None:
        return tier
    return ChatTier.FAST


def assistant_task(assistant: Assistant, tier: ChatTier | None = None) -> AiTask:
    """The AI task a chat of this assistant (and tier) runs as."""
    if assistant is Assistant.STUDENT:
        smart = effective_tier(assistant, tier) is ChatTier.SMART
        return AiTask.STUDENT_CHAT_SMART if smart else AiTask.STUDENT_CHAT
    if assistant is Assistant.LMS_AUTHOR:
        return AiTask.LMS_AUTHORING
    return AiTask.ADMIN_CHAT


def profile_for(
    assistant: Assistant,
    settings: Settings,
    tier: ChatTier | None = None,
    *,
    limits: LimitsSettings | ActorLimits | None = None,
) -> AssistantProfile:
    """Return the role, model profile and limits of an assistant.

    The limits are the ones of the user (`limits`, from the limits provider: overrides,
    extensions, staff); without them the environment's. The `smart` tier of the student
    assistant is its own task: it has its own model and budget weight
    (`AI__TASKS__STUDENT_CHAT_SMART__*`). The course author assistant runs as
    `AiTask.LMS_AUTHORING` with the `lms_ai_*` limits.
    """
    if limits is None:
        # Wrapped so that -1 (no cap) reads as None, like the provider's values.
        limits = ActorLimits(settings.limits, unlimited=False)
    llm = settings.ai_profile(assistant_task(assistant, tier))
    if assistant is Assistant.STUDENT:
        return AssistantProfile(
            assistant,
            Role.STUDENT,
            llm,
            limits.ai_session_tokens_student,
            limits.ai_daily_tokens_student,
            limits.ai_max_tool_steps,
        )
    if assistant is Assistant.LMS_AUTHOR:
        return AssistantProfile(
            assistant,
            None,
            llm,
            limits.lms_ai_session_tokens,
            limits.lms_ai_daily_tokens,
            limits.lms_ai_max_tool_steps,
            course_pool=True,
        )
    return AssistantProfile(
        assistant,
        Role.ADMIN,
        llm,
        None,
        None,
        limits.ai_max_tool_steps,
    )


def require_assistant_role(actor: Actor, assistant: Assistant) -> None:
    """Raise WrongAssistantError unless the actor's roles allow the assistant.

    The course author assistant has no global role; its per-course check is the
    `AuthorGate` (see `ChatGuard`).
    """
    role = ASSISTANT_ROLE.get(assistant)
    if role is not None and not actor.has(role):
        raise WrongAssistantError(params={"assistant": assistant.value})
