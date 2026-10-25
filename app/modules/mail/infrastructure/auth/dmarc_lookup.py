"""Find the DMARC record of a From domain (RFC 7489 section 6.6.3)."""

from app.modules.mail.domain.dmarc import (
    DmarcRecord,
    organizational_domain,
    select_record,
)
from app.modules.mail.ports.txt_resolver import TxtResolver


async def lookup_dmarc_record(
    resolver: TxtResolver, from_domain: str
) -> DmarcRecord | None:
    """Look up ``_dmarc.<domain>``, then ``_dmarc.<organizational domain>``.

    Raises:
        DnsTemporaryError: the DNS did not answer (the caller treats it as unknown).
    """
    texts = await resolver.txt(f"_dmarc.{from_domain}")
    record = select_record(texts, at_organizational_domain=False)
    if record is not None:
        return record
    organizational = organizational_domain(from_domain)
    if organizational == from_domain:
        return None
    texts = await resolver.txt(f"_dmarc.{organizational}")
    return select_record(texts, at_organizational_domain=True)
