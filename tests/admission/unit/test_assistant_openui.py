"""ADM-OUI: OpenUI blocks in the admission assistant."""

from typing import Any

from app.modules.ai.domain.prompts import admission_openui_prompt
from app.settings_ai import AiSettings
from app.shared.ai_tasks import AiTask
from app.shared.openui.finalize import OpenUiFinalizer

VALID = 'root = Stack([c])\nc = Card("Next", [TextBlock("Send it")])\n'
BROKEN = "root = Stack([c])\nc = Card(1, 2, 3, 4, 5)\n"
UNSAFE = 'root = LinkList([{title: "x", url: "javascript:alert(1)"}])\n'


def fenced(source: str) -> str:
    return f"```openui\n{source}```"


class Llm:
    """Answers every repair with a fixed text, or fails."""

    def __init__(self, answer: str | None) -> None:
        """Remember the answer."""
        self.answer = answer
        self.calls = 0

    async def complete(self, **request: Any) -> dict[str, Any]:
        self.calls += 1
        if self.answer is None:
            raise RuntimeError("down")
        return {"text": fenced(self.answer), "tool_calls": [], "usage": {}}


def finalizer(llm: Llm, enabled: bool = True) -> OpenUiFinalizer:
    profile = AiSettings().profile(AiTask.OPENUI_REPAIR)
    return OpenUiFinalizer(llm, profile, enabled=enabled)  # type: ignore[arg-type]


async def test_valid_block_passes_without_repair() -> None:
    """ADM-OUI-1: a valid block is kept and no model call is made."""
    llm = Llm(VALID)
    text = f"Steps:\n{fenced(VALID)}"
    assert await finalizer(llm).finalize(text) == text
    assert llm.calls == 0


async def test_invalid_block_gets_one_repair() -> None:
    """ADM-OUI-2: an invalid block is repaired once."""
    llm = Llm(VALID)
    out = await finalizer(llm).finalize(f"Steps:\n{fenced(BROKEN)}")
    assert llm.calls == 1
    assert "Send it" in out


async def test_failed_repair_falls_back_to_markdown() -> None:
    """ADM-OUI-3: a failed repair drops the block and keeps the text."""
    out = await finalizer(Llm(None)).finalize(f"Steps:\n{fenced(BROKEN)}\nEnd.")
    assert "openui" not in out
    assert "Steps:" in out and "End." in out


async def test_unsafe_link_never_survives() -> None:
    """ADM-OUI-4: a javascript: link does not reach the stored answer."""
    out = await finalizer(Llm(UNSAFE)).finalize(f"Links:\n{fenced(UNSAFE)}")
    assert "javascript:" not in out


async def test_disabled_finalizer_is_a_no_op_switch() -> None:
    """ADM-OUI-5: the admission switch defaults on, global one stays off."""
    settings = AiSettings()
    assert settings.openui_admission_enabled is True
    assert settings.openui_enabled is False


def test_prompt_lists_only_admission_components() -> None:
    """ADM-OUI-6: the prompt names the allowed blocks and no charts."""
    prompt = admission_openui_prompt()
    assert "- Card(" in prompt and "- LinkList(" in prompt
    assert "- BarChart(" not in prompt and "- Timetable(" not in prompt
