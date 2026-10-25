"""The real client address behind the edge proxy.

X-Forwarded-For is believed only when the TCP peer is a trusted proxy (the edge nginx,
given in ``IHSP_HTTP__TRUSTED_PROXIES``). Otherwise the peer is the client, so a client
cannot pick its own address to dodge the per-IP limits.
"""

import ipaddress
from collections.abc import Sequence
from functools import lru_cache

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=16)
def parse_trusted_proxies(value: str) -> tuple[IPNetwork, ...]:
    """Parse a comma list of IPs and CIDR networks; anything else raises ValueError."""
    networks: list[IPNetwork] = []
    for item in value.split(","):
        text = item.strip()
        if text:
            networks.append(ipaddress.ip_network(text, strict=False))
    return tuple(networks)


def _within(address: str, networks: Sequence[IPNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip.version == net.version and ip in net for net in networks)


def client_address(
    peer: str | None, forwarded_for: str | None, trusted: Sequence[IPNetwork]
) -> str | None:
    """Return the client: the peer, unless the peer is a trusted proxy.

    The proxy appends the hops it saw, so the list reads left (client) to right
    (nearest proxy). Walking from the right, the first address that is not a trusted
    proxy is the client. Anything unparsable falls back to the peer.
    """
    if peer is None or not forwarded_for or not _within(peer, trusted):
        return peer
    for hop in reversed([part.strip() for part in forwarded_for.split(",")]):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            return peer
        if not any(
            address.version == net.version and address in net for net in trusted
        ):
            return str(address)
    return peer
