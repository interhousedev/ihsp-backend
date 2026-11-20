"""The AI harness read tools over the use cases (no MCP transport)."""

from types import SimpleNamespace

from app.bootstrap.adapters.admin_tools import READ_TOOLS
from app.bootstrap.adapters.admin_tools_ai import MAX_DIFF_CHARS
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id

import pytest

ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))


class FakeAnalytics:
    def __init__(self) -> None:
        self.seen: dict[str, object] = {}

    async def spend(self, actor: Actor, **kw: object) -> dict[str, object]:
        self.seen = kw
        return {"items": [], "total_cost_micro": 0}


class FakeAdmin:
    async def diff(self, actor: Actor, task: str, name: str, **kw: object) -> object:
        from app.modules.ai.domain.requests import PromptDiff

        return PromptDiff(
            task=task,
            name=name,
            locale="",
            from_version=0,
            to_version=1,
            diff="+" * (MAX_DIFF_CHARS + 5),
            chars_delta=1,
            tokens_delta=1,
        )


def _container() -> SimpleNamespace:
    analytics = FakeAnalytics()
    return SimpleNamespace(
        ai=SimpleNamespace(
            analytics=analytics, prompts=SimpleNamespace(admin=FakeAdmin())
        )
    )


async def test_spend_defaults_and_limit() -> None:
    c = _container()

    await READ_TOOLS["ai_spend"](c, {"limit": 5}, ADMIN)  # type: ignore[arg-type]

    assert c.ai.analytics.seen["by"] == "day"
    assert c.ai.analytics.seen["limit"] == 5


async def test_a_bad_grouping_is_invalid() -> None:
    with pytest.raises(ValidationFailedError):
        await READ_TOOLS["ai_spend"](
            _container(), {"by": "mood"}, ADMIN  # type: ignore[arg-type]
        )


async def test_a_long_diff_is_truncated() -> None:
    out = await READ_TOOLS["ai_prompt_diff"](
        _container(), {"task": "t", "name": "n"}, ADMIN  # type: ignore[arg-type]
    )

    assert out["truncated"] is True
    assert len(out["diff"]) == MAX_DIFF_CHARS
