"""Request and response models of the AI endpoints (field names = API contract)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from app.interfaces.http.v1.agent_steps import AgentStepResponse
from app.interfaces.http.v1.web_search.schemas import WebResultResponse
from app.modules.ai.application.budget import UsageInfo
from app.modules.ai.application.views import (
    ChatDetailView,
    ChatItemView,
    TurnResultView,
)

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssistantName = Literal["student", "admin", "lms_author"]
TierName = Literal["fast", "smart"]


class CreateChatBody(BaseModel):
    """POST /v1/ai/chats; `tier` only matters for the student assistant."""

    assistant: AssistantName
    tier: TierName | None = None
    course_id: UUID | None = None
    """Required for `lms_author` (422 `ai/course-required` without it): the course
    the chat works on; the caller needs the course's ``edit`` permission (403)."""


class RenameChatBody(BaseModel):
    """PATCH /v1/ai/chats/{id}."""

    title: str = Field(min_length=1, max_length=120)


class SendMessageBody(BaseModel):
    """POST /v1/ai/chats/{id}/messages."""

    text: str = Field(default="", max_length=8000)
    command: str | None = Field(default=None, min_length=1, max_length=32)
    """A slash command (`cards`, `quiz`, ...) with its `args`; the agent maps it to a
    prompt or tool (422 `ai/unknown-command` for a name it does not know). Typed
    `/cards topic` in `text` works the same."""
    args: str = Field(default="", max_length=8000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=5)
    web_search: bool = False
    """Answer with a web search: spends one of today's searches (404 when the feature
    is off, 429 when they are used up, 503 when the provider fails)."""

    @model_validator(mode="after")
    def _needs_text_or_command(self) -> Self:
        if not self.text.strip() and not self.command:
            raise ValueError("text or command is required")
        return self


class RejectToolCallBody(BaseModel):
    """POST /v1/ai/chats/{id}/tool-calls/{call_id}/reject."""

    reason: str | None = Field(default=None, max_length=500)


class MessageFeedbackBody(BaseModel):
    """POST /v1/ai/chats/{id}/messages/{seq}/feedback."""

    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ChatItemResponse(_Response):
    """ChatItem."""

    id: UUID
    assistant: AssistantName
    title: str
    last_message_at: datetime
    pending_approvals: int
    tier: TierName
    course_id: UUID | None = None
    """The course of an `lms_author` chat; null for the other assistants."""

    @classmethod
    def from_view(cls, view: ChatItemView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)


class PreviewFieldResponse(_Response):
    """One field of an approval card."""

    label: str
    value: str
    sensitive: bool


class PreviewResponse(_Response):
    """An approval card."""

    title: str
    fields: list[PreviewFieldResponse]
    items: list[str]


class DocumentCardResponse(_Response):
    """A document the assistant made (shown as a file card)."""

    file_id: UUID
    name: str
    kind: Literal["docx", "xlsx", "pptx"]
    size: int


class ToolCallViewResponse(_Response):
    """ToolCallView."""

    id: str
    tool: str
    access: Literal["read", "write"]
    status: Literal[
        "running",
        "pending_approval",
        "rejected",
        "expired",
        "superseded",
        "done",
        "failed",
    ]
    note: str
    preview: PreviewResponse | None
    reject_reason: str | None
    expires_at: datetime | None
    document: DocumentCardResponse | None = None


class ChatMessageViewResponse(_Response):
    """ChatMessageView."""

    seq: int
    role: Literal["user", "assistant"]
    text: str
    file_ids: list[UUID]
    tool_calls: list[ToolCallViewResponse]
    created_at: datetime
    feedback: Literal["up", "down"] | None
    web: list[WebResultResponse]
    """Pages of the message's web search; `⟦w1⟧` chips in the text point at them."""
    steps: list[AgentStepResponse] = Field(default_factory=list)
    """What the assistant did while answering, in order (AI-STEPS)."""
    progress: list[str] = Field(default_factory=list)
    """The short notes the assistant wrote between its tool rounds, oldest first."""


class UsagePartResponse(_Response):
    """Tokens used against a limit."""

    used: int
    limit: int | None
    """None: the assistant has no cap (Administration)."""
    resets_at: datetime | None


class UsageInfoResponse(_Response):
    """UsageInfo."""

    session: UsagePartResponse
    day: UsagePartResponse
    smart_remaining: int | None = None
    """Smart-tier requests left this week; null when unlimited (staff) or when the
    assistant has no smart tier."""
    smart_limit: int | None = None
    """Smart-tier requests a week; null when unlimited or no smart tier."""
    smart_resets_at: datetime | None = None
    """When the smart requests of the week reset (Monday 00:00 Tashkent)."""

    @classmethod
    def from_view(cls, view: UsageInfo) -> Self:
        """Build from the budget view."""
        smart = view.smart
        return cls.model_validate(
            {
                "session": view.session,
                "day": view.day,
                "smart_remaining": smart.remaining if smart else None,
                "smart_limit": smart.limit if smart else None,
                "smart_resets_at": smart.resets_at if smart else None,
            }
        )


class ChatDetailResponse(ChatItemResponse):
    """ChatDetail = ChatItem plus messages and the shared flag."""

    messages: list[ChatMessageViewResponse]
    shared: bool

    @classmethod
    def from_detail(cls, view: ChatDetailView) -> Self:
        """Build from the use case view."""
        return cls(
            **ChatItemResponse.from_view(view.chat).model_dump(),
            messages=[ChatMessageViewResponse.model_validate(m) for m in view.messages],
            shared=view.shared,
        )


class TurnResultResponse(_Response):
    """TurnResult."""

    chat: ChatItemResponse
    new_messages: list[ChatMessageViewResponse]
    status: Literal["done", "awaiting_approval", "limit_reached"]
    usage: UsageInfoResponse

    @classmethod
    def from_view(cls, view: TurnResultView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)
