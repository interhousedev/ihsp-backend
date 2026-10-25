"""Per-peer limits of the inbound SMTP server (MAIL-9).

One process serves SMTP, so the counters live in memory. A peer that keeps naming
unknown mailboxes is told to come back later for every recipient (no more
`550 5.1.1` answers that would confirm which logins exist), and a peer that sends
too many messages in the window is slowed down the same way.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

UNKNOWN_RECIPIENTS_PER_WINDOW = 20
MESSAGES_PER_WINDOW = 100
WINDOW_SECONDS = 600
MAX_PEERS = 10_000  # bound on memory; the oldest windows are dropped first


@dataclass
class _Window:
    started: float
    unknown: int = 0
    messages: int = 0


@dataclass
class PeerLimiter:
    """Fixed-window counters per peer address."""

    unknown_limit: int = UNKNOWN_RECIPIENTS_PER_WINDOW
    messages_limit: int = MESSAGES_PER_WINDOW
    window_seconds: float = WINDOW_SECONDS
    now: Callable[[], float] = time.monotonic
    _peers: dict[str, _Window] = field(default_factory=dict, init=False, repr=False)

    def rcpt_blocked(self, ip: str) -> bool:
        """True while the peer has named too many unknown mailboxes."""
        return self._window(ip).unknown >= self.unknown_limit

    def unknown_recipient(self, ip: str) -> None:
        """Count one refused recipient of the peer."""
        self._window(ip).unknown += 1

    def message_allowed(self, ip: str) -> bool:
        """Count one message of the peer; False when the peer is over the limit."""
        window = self._window(ip)
        if window.messages >= self.messages_limit:
            return False
        window.messages += 1
        return True

    def _window(self, ip: str) -> _Window:
        moment = self.now()
        window = self._peers.get(ip)
        if window is None or moment - window.started >= self.window_seconds:
            self._prune(moment)
            window = _Window(started=moment)
            self._peers[ip] = window
        return window

    def _prune(self, moment: float) -> None:
        expired = [
            ip
            for ip, window in self._peers.items()
            if moment - window.started >= self.window_seconds
        ]
        for ip in expired:
            del self._peers[ip]
        while len(self._peers) >= MAX_PEERS:
            del self._peers[next(iter(self._peers))]
