"""Per-assistant configuration: role, model and token limits."""

from dataclasses import dataclass

from app.modules.ai.domain.assistant import ASSISTANT_ROLE, Assistant
from app.modules.ai.domain.errors import WrongAssistantError
from app.settings import Settings
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class AssistantProfile:
    """What differs between the student and the Administration assistant."""

    assistant: Assistant
    role: Role
    model: str
    session_tokens: int
    daily_tokens: int


def profile_for(assistant: Assistant, settings: Settings) -> AssistantProfile:
    """Return the role, model and limits of an assistant from the settings."""
    limits = settings.limits
    if assistant is Assistant.STUDENT:
        return AssistantProfile(
            assistant,
            Role.STUDENT,
            settings.openrouter.model_student,
            limits.ai_session_tokens_student,
            limits.ai_daily_tokens_student,
        )
    return AssistantProfile(
        assistant,
        Role.ADMIN,
        settings.openrouter.model_admin,
        limits.ai_session_tokens_admin,
        limits.ai_daily_tokens_admin,
    )


def require_assistant_role(actor: Actor, assistant: Assistant) -> None:
    """Raise WrongAssistantError unless the actor may use the assistant."""
    if not actor.has(ASSISTANT_ROLE[assistant]):
        raise WrongAssistantError(params={"assistant": assistant.value})
