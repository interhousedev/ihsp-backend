"""SPF + DKIM + DMARC of an inbound message (MAIL-9)."""

import asyncio

from app.modules.mail.domain.addresses import address_domain
from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.dmarc import DmarcResult, evaluate_dmarc
from app.modules.mail.domain.inbound_message import parse_headers
from app.modules.mail.infrastructure.auth.dkim_check import (
    DkimOutcome,
    DnsFunction,
    run_dkim,
)
from app.modules.mail.infrastructure.auth.dmarc_lookup import lookup_dmarc_record
from app.modules.mail.infrastructure.auth.spf_check import (
    SpfFunction,
    check_spf,
    run_spf,
)
from app.modules.mail.ports.txt_resolver import DnsTemporaryError, TxtResolver

import structlog

log = structlog.get_logger(__name__)


class DnsInboundAuthenticator:
    """Implements InboundAuthenticator; SPF and DKIM follow the settings toggles.

    DMARC needs both results, so it runs only when both checks are enabled.
    """

    def __init__(
        self,
        resolver: TxtResolver,
        *,
        enable_spf: bool,
        enable_dkim: bool,
        spf_function: SpfFunction = check_spf,
        dkim_dnsfunc: DnsFunction | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Store the toggles and the lookup functions (replaceable in tests)."""
        self._resolver = resolver
        self._enable_spf = enable_spf
        self._enable_dkim = enable_dkim
        self._spf_function = spf_function
        self._dkim_dnsfunc = dkim_dnsfunc
        self._timeout = timeout

    async def check(
        self, raw: bytes, *, peer_ip: str, mail_from: str, helo: str
    ) -> InboundChecks:
        """Run the enabled checks within the overall timeout."""
        if not (self._enable_spf or self._enable_dkim):
            return InboundChecks()
        try:
            return await asyncio.wait_for(
                self._run(raw, peer_ip, mail_from, helo), self._timeout
            )
        except TimeoutError:
            log.warning("inbound_checks_timeout", peer_ip=peer_ip)
            return InboundChecks(spf="temperror" if self._enable_spf else "none")

    async def _run(
        self, raw: bytes, peer_ip: str, mail_from: str, helo: str
    ) -> InboundChecks:
        sender = mail_from or f"postmaster@{helo}"
        spf_domain = address_domain(sender)
        spf_result = "none"
        dkim = DkimOutcome()
        if self._enable_spf:
            spf_result = await run_spf(
                self._spf_function, peer_ip, sender, helo, self._timeout
            )
        if self._enable_dkim:
            dkim = await run_dkim(raw, self._dkim_dnsfunc, self._timeout)
        from_domain = address_domain(parse_headers(raw).from_address)
        dmarc = DmarcResult(result="none")
        if self._enable_spf and self._enable_dkim and from_domain:
            passed = spf_domain if spf_result == "pass" else None
            dmarc = await self._dmarc(from_domain, passed, dkim)
        return InboundChecks(
            spf=spf_result,
            dkim=dkim.result,
            dmarc=dmarc.result,
            dmarc_policy=None if dmarc.policy is None else dmarc.policy.value,
            spf_domain=spf_domain,
            dkim_domains=dkim.domains,
            from_domain=from_domain,
        )

    async def _dmarc(
        self, from_domain: str, spf_pass_domain: str | None, dkim: DkimOutcome
    ) -> DmarcResult:
        try:
            record = await lookup_dmarc_record(self._resolver, from_domain)
        except DnsTemporaryError:
            log.warning("dmarc_lookup_failed", from_domain=from_domain)
            return DmarcResult(result="none")
        return evaluate_dmarc(
            record,
            from_domain=from_domain,
            spf_pass_domain=spf_pass_domain,
            dkim_pass_domains=dkim.domains,
        )
