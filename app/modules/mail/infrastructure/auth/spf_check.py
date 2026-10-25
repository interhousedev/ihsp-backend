"""SPF with pyspf (blocking DNS, so it runs in a thread)."""

import asyncio
from collections.abc import Callable

import spf

SpfFunction = Callable[[str, str, str], str]
QUERY_SECONDS = 10


def check_spf(peer_ip: str, sender: str, helo: str) -> str:
    """Return the SPF result (pass, fail, softfail, neutral, none, ...errors)."""
    try:
        result, _ = spf.check2(peer_ip, sender, helo, querytime=QUERY_SECONDS)
    except spf.TempError:
        return "temperror"
    except (spf.PermError, ValueError):
        return "permerror"
    return str(result).lower()


async def run_spf(
    function: SpfFunction, peer_ip: str, sender: str, helo: str, timeout: float
) -> str:
    """Run the check off the event loop; a timeout is a temporary error."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(function, peer_ip, sender, helo), timeout
        )
    except TimeoutError:
        return "temperror"
