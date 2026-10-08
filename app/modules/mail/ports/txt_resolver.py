"""DNS TXT lookups for DMARC."""

from typing import Protocol


class DnsTemporaryError(Exception):
    """The DNS server did not answer in time (the result stays unknown)."""


class TxtResolver(Protocol):
    """Looks up TXT records."""

    async def txt(self, name: str) -> list[str]:
        """Return the joined strings of every TXT record; [] when there are none.

        Raises:
            DnsTemporaryError: timeout or server failure.
        """
        ...
