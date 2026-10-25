"""TXT lookups with dnspython's asyncio resolver."""

from typing import Any

from app.modules.mail.ports.txt_resolver import DnsTemporaryError

import dns.asyncresolver
import dns.exception
import dns.name
import dns.resolver

_NO_RECORDS = (
    dns.resolver.NXDOMAIN,
    dns.resolver.NoAnswer,
    dns.name.NameTooLong,
    dns.name.LabelTooLong,
    dns.name.EmptyLabel,
)


class DnsTxtResolver:
    """Implements TxtResolver over the system's DNS servers."""

    def __init__(self, *, lifetime: float = 5.0) -> None:
        """Set the time one lookup may take (all retries included)."""
        self._lifetime = lifetime

    async def txt(self, name: str) -> list[str]:
        """Return the joined strings of every TXT record of the name."""
        resolver = dns.asyncresolver.Resolver()
        try:
            answer = await resolver.resolve(name, "TXT", lifetime=self._lifetime)
        except _NO_RECORDS:
            return []
        except dns.exception.DNSException as exc:
            raise DnsTemporaryError(f"{name}: {exc}") from exc
        records: list[str] = []
        rdata: Any
        for rdata in answer:
            records.append(b"".join(rdata.strings).decode("utf-8", "replace"))
        return records
