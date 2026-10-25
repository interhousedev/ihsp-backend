"""Results of the inbound authentication checks, stored in ``meta.checks``."""

from pydantic import BaseModel, ConfigDict


class InboundChecks(BaseModel):
    """SPF, DKIM and DMARC results of one received message (MAIL-9).

    ``spf`` is a pyspf result (pass, fail, softfail, neutral, none, temperror,
    permerror); ``dkim`` and ``dmarc`` are pass, fail or none (none = not checked or
    nothing to check).
    """

    model_config = ConfigDict(frozen=True)

    spf: str = "none"
    dkim: str = "none"
    dmarc: str = "none"
    dmarc_policy: str | None = None
    spf_domain: str | None = None
    dkim_domains: tuple[str, ...] = ()
    from_domain: str | None = None
