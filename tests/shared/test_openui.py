"""OpenUI blocks in AI answers: parse, validate, repair, drop, degrade (AI-OPENUI)."""

from typing import Any

from app.shared.ai_access import AI_TASK_SCOPE
from app.shared.ai_tasks import TASK_SPECS, AiTask
from app.shared.openui.blocks import split_blocks
from app.shared.openui.catalog import load_catalog
from app.shared.openui.degrade import degrade_to_markdown
from app.shared.openui.finalize import OpenUiFinalizer
from app.shared.openui.prompt import openui_prompt
from app.shared.openui.validate import validate_block

import pytest

VALID = (
    "root = Stack([stats, chart])\n"
    'stats = StatGrid([{label: "Average", value: 4.5}, '
    '{label: "Lessons", value: 12}])\n'
    'chart = BarChart(["Mon", "Tue"], [3, 5], "Marks")\n'
)
BROKEN = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"])\n'
UNSAFE = (
    "root = Stack([links])\n"
    'links = LinkList([{title: "Bad", url: "javascript:alert(1)"}])\n'
)


def fenced(source: str) -> str:
    return f"```openui\n{source}```"


class FakeRepairLlm:
    """Answers `complete` with a fixed text and records the requests."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[dict[str, Any]] = []

    async def complete(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"text": self.answer, "tool_calls": [], "usage": {}}


def finalizer(llm: FakeRepairLlm, *, enabled: bool = True) -> OpenUiFinalizer:
    from app.settings_ai import AiSettings

    profile = AiSettings().profile(AiTask.OPENUI_REPAIR)
    return OpenUiFinalizer(llm, profile, enabled=enabled)  # type: ignore[arg-type]


def test_valid_block_has_no_errors() -> None:
    """AI-OPENUI: a block built from the catalog validates."""
    assert validate_block(VALID) == []


def test_missing_required_prop_is_an_error() -> None:
    """AI-OPENUI: a chart without values is invalid."""
    errors = validate_block(BROKEN)
    assert any("values" in error for error in errors)


@pytest.mark.parametrize(
    "source",
    [
        'root = Stack([x])\nx = Unknown("a")\n',
        "root = Stack([x])\nx = TextBlock($state)\n",
        "root = Stack([x])\nx = TextBlock(@Count(a))\n",
        'chart = BarChart(["a"], [1])\n',  # no root
        "root = Stack([missing])\n",
        'root = Stack([TextBlock("<script>alert(1)</script>")])\n',
    ],
)
def test_unsupported_or_unsafe_syntax_is_rejected(source: str) -> None:
    """AI-OPENUI: unknown components, state, functions, scripts and holes fail."""
    assert validate_block(source) != []


def test_unsafe_link_is_an_error() -> None:
    """AI-OPENUI: links are https only."""
    assert any("https" in error for error in validate_block(UNSAFE))


def test_studio_subset_refuses_chat_only_components() -> None:
    """AI-OPENUI: Studio items may only use the small subset."""
    source = 'root = Stack([l])\nl = LinkList([{title: "a", url: "https://a.uz"}])\n'
    assert validate_block(source, subset="studio") != []
    assert validate_block('root = Table(["a"], [["1"]])\n', subset="studio") == []


def test_split_finds_text_and_blocks() -> None:
    """AI-OPENUI: answers are text with fenced blocks."""
    parts = split_blocks(f"Here:\n{fenced(VALID)}\nDone.")
    assert [part.kind for part in parts] == ["text", "block", "text"]
    assert parts[1].text == VALID


async def test_valid_block_passes_through_without_a_model_call() -> None:
    """AI-OPENUI: a valid block is kept as it is."""
    llm = FakeRepairLlm("")
    text = f"Your week:\n{fenced(VALID)}\nKeep going."
    assert await finalizer(llm).finalize(text) == text
    assert llm.requests == []


async def test_invalid_block_is_repaired() -> None:
    """AI-OPENUI: a broken block goes to the cheap repair task and is replaced."""
    llm = FakeRepairLlm(fenced(VALID))
    result = await finalizer(llm).finalize(f"Look:\n{fenced(BROKEN)}")
    assert result == f"Look:\n{fenced(VALID)}"
    request = llm.requests[0]
    assert request["tuning"].task == "openui_repair"
    assert "values" in request["messages"][0]["content"]


async def test_unrepairable_block_is_dropped_and_text_kept() -> None:
    """AI-OPENUI: when the repair is still invalid, only the text stays."""
    llm = FakeRepairLlm("not a block at all")
    result = await finalizer(llm).finalize(f"Look:\n{fenced(BROKEN)}\nThe end.")
    assert "openui" not in result
    assert "Look:" in result and "The end." in result


async def test_unsafe_link_is_stripped() -> None:
    """AI-OPENUI: a block with a javascript: link never survives."""
    llm = FakeRepairLlm(fenced(UNSAFE))
    result = await finalizer(llm).finalize(f"Links:\n{fenced(UNSAFE)}")
    assert "javascript" not in result


async def test_disabled_flag_leaves_text_alone() -> None:
    """AI-OPENUI: with the flag off nothing is called."""
    llm = FakeRepairLlm("")
    text = f"a\n{fenced(BROKEN)}"
    assert await finalizer(llm, enabled=False).finalize(text) == text
    assert llm.requests == []


def test_degrade_to_markdown_for_telegram() -> None:
    """AI-OPENUI: Telegram gets readable text instead of a block."""
    links = (
        'root = Stack([l])\nl = LinkList([{title: "Site", url: "https://iht.uz"}])\n'
    )
    text = degrade_to_markdown(f"Hi\n{fenced(VALID)}\n{fenced(links)}")
    assert "```" not in text
    assert "Average" in text and "4.5" in text
    assert "Mon" in text and "5" in text
    assert "[Site](https://iht.uz)" in text


def test_degrade_hides_unfinished_and_invalid_blocks() -> None:
    """AI-OPENUI: a half-streamed or broken block is not shown as code."""
    assert "BarChart" not in degrade_to_markdown("Hi\n```openui\nroot = Stack([")
    assert "BarChart" not in degrade_to_markdown(f"Hi\n{fenced(BROKEN)}")


def test_prompt_lists_the_catalog() -> None:
    """AI-OPENUI: the model is taught every allowed component."""
    prompt = openui_prompt()
    for component in load_catalog().components:
        assert component.name in prompt
    assert "```openui" in prompt


def test_repair_task_is_cheap_and_counts_as_chat() -> None:
    """AI-OPENUI: the repair task is a chat-scope task without reasoning."""
    spec = TASK_SPECS[AiTask.OPENUI_REPAIR]
    assert spec.reasoning_effort == "none"
    assert spec.model is not None and "qwen" in spec.model
    assert AI_TASK_SCOPE[AiTask.OPENUI_REPAIR] == "chat"
