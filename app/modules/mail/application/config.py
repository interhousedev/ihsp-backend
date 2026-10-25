"""Plain configuration of the mail use cases (built from Settings in wiring)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MailConfig:
    """Mail domain, limits and retention."""

    mail_domain: str
    recipients_limit: int
    per_day_limit: int
    global_per_day_limit: int
    max_inbound_recipients: int = 20
    retention_days: int = 30
