"""The `AgentStep` response shared by the AI chats and the notebook chat (AI-STEPS)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AgentStepResponse(BaseModel):
    """AgentStep: one action of the assistant while it answered.

    `target` is a name to show (a file, a count of results); `ref` an id the web can
    open (a file id, a tool call id, a plan id).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: Literal[
        "read_file", "web_search", "retrieve", "open_view", "create", "tool", "think"
    ]
    label: str
    target: str | None = None
    ref: str | None = None
    status: Literal["running", "done", "failed"]
    started_at: datetime | None = None
    duration_ms: int | None = None
