"""Maintenance mode: bot writes are refused with a notice, reads keep working."""

from types import SimpleNamespace

from app.shared.maintenance import MaintenanceInfo
from tests.bot.support.harness import Harness


class Gate:
    """A maintenance gate that is on."""

    def info(self) -> MaintenanceInfo:
        return MaintenanceInfo(active=True)


def enable(harness: Harness) -> str:
    """Switch maintenance on; return the notice in the student's language (en)."""
    harness.world.container.admin = SimpleNamespace(migration=Gate())
    return harness.world.i18n.t("en", "error-maintenance")


async def test_an_assistant_message_is_refused(harness: Harness) -> None:
    """A plain text (a model call) gets the notice and no assistant answer."""
    notice = enable(harness)

    await harness.send("What is homework today?")

    assert harness.last_text() == notice
    assert len(harness.sent) == 1


async def test_a_mutating_callback_is_refused(harness: Harness) -> None:
    """A settings change answers with the notice as an alert."""
    notice = enable(harness)

    await harness.press("st:lang:uz")

    assert [t.text for t in harness.toasts] == [notice]


async def test_reads_keep_working(harness: Harness) -> None:
    """Commands and screens still answer normally."""
    notice = enable(harness)

    await harness.send("/menu")
    await harness.press("st:open:x")

    assert notice not in {m.text for m in harness.sent}
    assert harness.sent
    assert all(t.text != notice for t in harness.toasts)
