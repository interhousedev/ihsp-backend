"""A scripted stand-in for the feedback module's submit use case."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.shared.base_error import BaseError
from app.shared.ids import new_id

RATE_LIMITED_CODE = "feedback/rate-limited"


class FeedbackRateLimited(BaseError):
    """The user sent 10 reports today."""

    code = RATE_LIMITED_CODE
    status = 429
    message_key = "bot-feedback-rate-limited"


class FakeFeedback:
    """FeedbackServices.submit: records the reports and can refuse them."""

    def __init__(self) -> None:
        """No reports yet, and no rate limit."""
        self.submitted: list[dict[str, Any]] = []
        self.rate_limited = False

    async def submit(
        self,
        actor: Any,
        kind: str,
        area: str,
        title: str,
        description: str,
        attachment_file_ids: list[UUID],
        source: str = "bot",
    ) -> SimpleNamespace:
        """Record the report, or refuse it when the limit is reached."""
        if self.rate_limited:
            raise FeedbackRateLimited()
        self.submitted.append(
            {
                "actor": actor,
                "kind": kind,
                "area": area,
                "title": title,
                "description": description,
                "files": list(attachment_file_ids),
                "source": source,
            }
        )
        return SimpleNamespace(id=new_id())
