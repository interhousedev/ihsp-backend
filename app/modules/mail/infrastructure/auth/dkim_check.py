"""DKIM verification with dkimpy (blocking DNS, so it runs in a thread)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dkim

MAX_SIGNATURES = 3
DnsFunction = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class DkimOutcome:
    """pass/fail/none and the ``d=`` domains of the signatures that verified."""

    result: str = "none"
    domains: tuple[str, ...] = ()


def verify_dkim(raw: bytes, dnsfunc: DnsFunction | None = None) -> DkimOutcome:
    """Verify up to three signatures; none without a DKIM-Signature header."""
    try:
        total = sum(1 for name, _ in dkim.DKIM(raw).headers if _is_signature(name))
    except (dkim.DKIMException, ValueError):
        return DkimOutcome(result="fail")
    if total == 0:
        return DkimOutcome()
    domains: list[str] = []
    for index in range(min(total, MAX_SIGNATURES)):
        domain = _verify_one(raw, index, dnsfunc)
        if domain is not None:
            domains.append(domain)
    return DkimOutcome(
        result="pass" if domains else "fail", domains=tuple(dict.fromkeys(domains))
    )


def _is_signature(name: bytes) -> bool:
    return bool(name.lower() == b"dkim-signature")


def _verify_one(raw: bytes, index: int, dnsfunc: DnsFunction | None) -> str | None:
    try:
        verifier = dkim.DKIM(raw)
        ok = (
            verifier.verify(index)
            if dnsfunc is None
            else verifier.verify(index, dnsfunc=dnsfunc)
        )
    except (dkim.DKIMException, ValueError, KeyError):
        return None
    if not ok or not verifier.domain:
        return None
    return str(verifier.domain.decode("ascii", "ignore").lower())


async def run_dkim(
    raw: bytes, dnsfunc: DnsFunction | None, timeout: float
) -> DkimOutcome:
    """Run the verification off the event loop; a timeout counts as failure."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(verify_dkim, raw, dnsfunc), timeout
        )
    except TimeoutError:
        return DkimOutcome(result="fail")
