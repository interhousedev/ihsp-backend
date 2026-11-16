"""cancel_pending semantics of the in-memory outbox (the SQL one is one UPDATE)."""

from types import SimpleNamespace

from tests.fakes.outbox import InMemoryOutbox


async def test_pending_cancels_once() -> None:
    """A pending row cancels; a second cancel finds nothing."""
    outbox = InMemoryOutbox()
    row = SimpleNamespace(dedupe_key="k")
    outbox.notifications.append(row)  # type: ignore[arg-type]
    assert await outbox.cancel_pending(None, "k") is True  # type: ignore[arg-type]
    assert await outbox.cancel_pending(None, "k") is False  # type: ignore[arg-type]


async def test_claimed_row_cannot_be_cancelled() -> None:
    """A row the worker already claimed is no longer cancellable."""
    outbox = InMemoryOutbox()
    outbox.claimed.add("k")
    assert await outbox.cancel_pending(None, "k") is False  # type: ignore[arg-type]
