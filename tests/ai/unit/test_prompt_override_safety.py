"""Override trial format on save, runtime warning, and the non-editable guard."""

from datetime import UTC, datetime
from uuid import uuid4

from app.bootstrap.adapters.prompt_slots import prompt_slots
from app.modules.admission.infrastructure.ai.prompts import items
from app.modules.ai.domain.prompt_registry import (
    ActiveOverrides,
    PromptSlot,
    PromptVersion,
    apply_overrides,
    check_override,
)

import pytest

_SLOT = PromptSlot("t", "s", "sum", "Hello {name}!", template=True)


def _version(slot: PromptSlot, text: str) -> PromptVersion:
    return PromptVersion(
        uuid4(), slot.task, slot.name, "", 1, text, "h", True,
        datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def test_nested_spec_is_rejected_on_save() -> None:
    assert check_override(_SLOT, "Hi {name:{name}}") == "bad_format"
    assert check_override(_SLOT, "Hi {name!z}") == "bad_format"
    assert check_override(_SLOT, "Hi {name}") is None


def test_runtime_format_failure_logs_and_falls_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    active = ActiveOverrides.of([_version(_SLOT, "Hi {name:{name}}")])
    out, ref = apply_overrides("Hello Bob!", "t", [_SLOT], active)
    assert out == "Hello Bob!" and ref is None
    assert "prompt_override_format_failed" in capsys.readouterr().out


def test_guard_is_appended_when_override_drops_it() -> None:
    slot = next(
        s
        for s in prompt_slots()
        if s.task == "admit_item_review" and s.name == "system"
    )
    assert slot.guard == items.SAFETY
    assert slot.builtin.count(items.SAFETY) == 1
    system = slot.builtin.format(
        kind="k", org_name="o", position_max=1, org_max=2, description_max=3,
        language="en", rubric="r",
    )  # fmt: skip
    own = "Grade {kind} for {org_name}. {position_max}{org_max}{description_max}"
    own += "{language}{rubric}"
    active = ActiveOverrides.of([_version(slot, own)])
    out, _ = apply_overrides(system, slot.task, [slot], active)
    assert out.endswith("\n" + items.SAFETY)
    kept = ActiveOverrides.of([_version(slot, own + items.SAFETY)])
    out2, _ = apply_overrides(system, slot.task, [slot], kept)
    assert out2.count(items.SAFETY) == 1
