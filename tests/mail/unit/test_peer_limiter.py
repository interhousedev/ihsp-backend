"""MAIL-9: per-peer limits of the inbound SMTP server."""

from app.interfaces.smtp.peer_limiter import MAX_PEERS, PeerLimiter


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_unknown_recipients_block_the_peer_until_the_window_ends() -> None:
    clock = _Clock()
    limiter = PeerLimiter(unknown_limit=3, window_seconds=600, now=clock)

    for _ in range(3):
        assert not limiter.rcpt_blocked("203.0.113.9")
        limiter.unknown_recipient("203.0.113.9")

    assert limiter.rcpt_blocked("203.0.113.9")
    assert not limiter.rcpt_blocked("203.0.113.10")  # another peer
    clock.t += 600
    assert not limiter.rcpt_blocked("203.0.113.9")


def test_messages_are_counted_per_window() -> None:
    clock = _Clock()
    limiter = PeerLimiter(messages_limit=2, window_seconds=600, now=clock)

    assert limiter.message_allowed("203.0.113.9")
    assert limiter.message_allowed("203.0.113.9")
    assert not limiter.message_allowed("203.0.113.9")
    assert limiter.message_allowed("203.0.113.10")
    clock.t += 601
    assert limiter.message_allowed("203.0.113.9")


def test_memory_is_bounded_and_expired_windows_are_dropped() -> None:
    clock = _Clock()
    limiter = PeerLimiter(window_seconds=600, now=clock)

    for n in range(MAX_PEERS + 5):
        limiter.unknown_recipient(f"10.{n >> 16 & 255}.{n >> 8 & 255}.{n & 255}")
    assert len(limiter._peers) <= MAX_PEERS  # noqa: SLF001

    clock.t += 600
    limiter.unknown_recipient("203.0.113.9")
    assert list(limiter._peers) == ["203.0.113.9"]  # noqa: SLF001
