"""The suggestion cards of a finished `admission_suggest` call reach the chat view."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.modules.ai.application.chat_views import ChatViews
from app.modules.ai.application.views import ToolCallView
from app.modules.ai.domain.tool_call import ToolAccess, ToolCall, ToolStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CARD = {
    "type": "university",
    "id": "u1",
    "title": "MIT",
    "reason": "Strong match",
    "link": "/universities/?id=u1",
}


def _view(tool: str, status: ToolStatus, result: dict | None) -> ToolCallView:
    i18n = MagicMock()
    i18n.t.return_value = "note"
    call = ToolCall(
        id="c1", tool=tool, access=ToolAccess.READ, status=status, result=result
    )
    return ChatViews(i18n).tool_call(call, "en", NOW)


def test_done_suggest_call_exposes_cards() -> None:
    view = _view("admission_suggest", ToolStatus.DONE, {"cards": [CARD, {"x": 1}]})
    assert [(c.type, c.id, c.title, c.reason) for c in view.cards] == [
        ("university", "u1", "MIT", "Strong match")
    ]


def test_other_tools_and_unfinished_calls_have_no_cards() -> None:
    assert _view("admission_suggest", ToolStatus.RUNNING, {"cards": [CARD]}).cards == []
    assert _view("get_application", ToolStatus.DONE, {"cards": [CARD]}).cards == []
