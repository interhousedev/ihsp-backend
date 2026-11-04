"""AI-OPENUI: repair size, counters and the token budget of the repair."""

from typing import Any

from app.settings_ai import AiSettings
from app.shared.ai_tasks import AiTask
from app.shared.openui.finalize import REPAIR_MAX_TOKENS, OpenUiFinalizer

from structlog.testing import capture_logs

BROKEN = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"])\n'
VALID = 'root = TextBlock("ok")\n'


def fenced(source: str) -> str:
    return f"```openui\n{source}```"


class FakeRepairLlm:
    """Answers `complete` with a fixed text and usage, and records the requests."""

    def __init__(self, answer: str, usage: dict[str, int] | None = None) -> None:
        self.answer = answer
        self.usage = usage or {}
        self.requests: list[dict[str, Any]] = []

    async def complete(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"text": self.answer, "tool_calls": [], "usage": self.usage}


def finalizer(llm: FakeRepairLlm) -> OpenUiFinalizer:
    profile = AiSettings().profile(AiTask.OPENUI_REPAIR)
    return OpenUiFinalizer(llm, profile, enabled=True)  # type: ignore[arg-type]


async def test_large_block_gets_a_cap_that_scales_with_its_length() -> None:
    """AI-OPENUI: a block longer than the fixed cap may still be answered in full."""
    block = BROKEN + 'note = TextBlock("' + "x" * 2300 + '")\n'
    llm = FakeRepairLlm(fenced(VALID))
    await finalizer(llm).finalize(f"Look:\n{fenced(block)}")
    cap = llm.requests[0]["max_tokens"]
    assert cap > REPAIR_MAX_TOKENS
    assert cap >= len(block) // 2


async def test_oversized_block_is_dropped_without_a_model_call() -> None:
    """AI-OPENUI: a block over the catalogue size limit is never sent to repair."""
    oversized = "x = 1\n" * 1100  # longer than max_block_chars
    llm = FakeRepairLlm(fenced(VALID))
    result = await finalizer(llm).finalize(f"Look:\n{fenced(oversized)}\nEnd.")
    assert llm.requests == []
    assert "openui" not in result
    assert "Look:" in result and "End." in result


async def test_repaired_and_dropped_blocks_are_logged() -> None:
    """AI-OPENUI: every repair and every drop leaves a log event for the counters."""
    with capture_logs() as logs:
        await finalizer(FakeRepairLlm(fenced(VALID))).finalize(f"a\n{fenced(BROKEN)}")
        await finalizer(FakeRepairLlm("nope")).finalize(f"a\n{fenced(BROKEN)}")
        await finalizer(FakeRepairLlm("")).finalize(f"a\n{fenced('x = 1\n' * 1100)}")
    events = [entry["event"] for entry in logs]
    assert events.count("openui.block_repaired") == 1
    assert events.count("openui.block_dropped") == 2
    dropped = [entry for entry in logs if entry["event"] == "openui.block_dropped"]
    assert {entry["reason"] for entry in dropped} == {"unrepairable", "oversized"}


async def test_repair_tokens_are_reported_to_the_budget() -> None:
    """AI-OPENUI: the tokens of a repair call are counted, so the budget sees them."""
    counted: list[int] = []

    async def count(tokens: int) -> None:
        counted.append(tokens)

    llm = FakeRepairLlm(fenced(VALID), usage={"input": 100, "output": 50})
    await finalizer(llm).finalize(f"a\n{fenced(BROKEN)}", count=count)
    assert counted == [150]


async def test_repair_without_usage_reports_nothing() -> None:
    """AI-OPENUI: a repair that reports no usage adds nothing to the budget."""
    counted: list[int] = []

    async def count(tokens: int) -> None:
        counted.append(tokens)

    llm = FakeRepairLlm(fenced(VALID))
    await finalizer(llm).finalize(f"a\n{fenced(BROKEN)}", count=count)
    assert counted == []
