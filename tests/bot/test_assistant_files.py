"""Uploads are attached only once the files module has processed them."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.artifact_notice import artifact_file
from app.interfaces.bot.assistant.media import FileNotReadyError, wait_ready
from app.shared.ids import new_id

import pytest


class Files:
    """Answers `get` with the queued statuses, then the last one forever."""

    def __init__(self, *statuses: str | None) -> None:  # noqa: D107
        self.statuses = list(statuses)
        self.calls = 0

    async def get(self, file_id: UUID) -> Any:
        self.calls += 1
        status = self.statuses[min(self.calls, len(self.statuses)) - 1]
        return None if status is None else SimpleNamespace(status=status)


class Clock:
    """Time moves only when the poller sleeps."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


async def test_waits_until_ready() -> None:
    files: Any = Files("pending", "processing", "ready")
    clock = Clock()

    await wait_ready(files, new_id(), sleep=clock.sleep, now=clock.now)

    assert files.calls == 3


async def test_gives_up_after_the_timeout() -> None:
    files: Any = Files("processing")
    clock = Clock()

    with pytest.raises(FileNotReadyError):
        await wait_ready(files, new_id(), timeout=30, sleep=clock.sleep, now=clock.now)

    assert clock.t == pytest.approx(30)


async def test_a_rejected_file_stops_at_once() -> None:
    files: Any = Files("rejected")
    clock = Clock()

    with pytest.raises(FileNotReadyError):
        await wait_ready(files, new_id(), sleep=clock.sleep, now=clock.now)

    assert files.calls == 1


class Notebooks:
    def __init__(self, found: dict[str, Any] | None) -> None:
        self.found = found

    async def get_artifact_content(self, *args: Any) -> dict[str, Any] | None:
        return self.found


async def test_a_ready_report_is_attached_as_a_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.interfaces.bot.assistant import artifact_notice

    monkeypatch.setattr(
        artifact_notice,
        "export_as",
        lambda kind, title, content, fmt: SimpleNamespace(
            name=f"{title}.{fmt}", data=b"# Optics"
        ),
    )
    found = {"kind": "report", "title": "Optics", "content": {}}
    payload = {"notebook_id": str(new_id()), "artifact_id": str(new_id())}

    attached = await artifact_file(Notebooks(found), new_id(), payload)

    assert attached is not None and attached[1] == b"# Optics"


async def test_an_output_that_is_gone_attaches_nothing() -> None:
    payload = {"notebook_id": str(new_id()), "artifact_id": str(new_id())}

    assert await artifact_file(Notebooks(None), new_id(), payload) is None
