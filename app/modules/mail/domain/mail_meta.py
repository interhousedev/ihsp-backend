"""Schema of the ``meta`` jsonb column of mail.mail_messages."""

from datetime import datetime
from typing import Any

from app.modules.mail.domain.checks import InboundChecks

from pydantic import BaseModel, ConfigDict, Field


class MailMeta(BaseModel):
    """Everything the module keeps about a mail beside its columns."""

    model_config = ConfigDict(extra="ignore")

    checks: InboundChecks | None = None
    spam_reasons: list[str] = Field(default_factory=list)
    skipped_attachments: list[str] = Field(default_factory=list)
    parsed_at: datetime | None = None
    purged: bool = False
    sent_at: datetime | None = None
    bounced_at: datetime | None = None
    bounce_reason: str | None = None
    failed_reason: str | None = None
    refused_recipients: list[str] = Field(default_factory=list)
    suspension_counted: bool = False

    def to_json(self) -> dict[str, Any]:
        """Return the JSON-compatible dict stored in the column (no empty values)."""
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
