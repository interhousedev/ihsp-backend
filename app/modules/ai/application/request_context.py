"""The AI request the current call runs for (read by the usage-recording gateway)."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestCtx:
    """The registered request of the running model call and its pipeline."""

    request_id: str
    pipeline: str


current_request: ContextVar[RequestCtx | None] = ContextVar(
    "ai_current_request", default=None
)
