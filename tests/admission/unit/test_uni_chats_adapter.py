"""The university chats adapter opens chats that do not spend smart requests."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.bootstrap.adapters.admission import AdmissionUniChatsAdapter
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatTier
from app.shared.actor import Actor

CHAT_ID = UUID("00000000-0000-7000-8000-000000000001")


class _Recorder:
    def __init__(self, result: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.result


async def test_start_creates_a_fast_tier_student_chat() -> None:
    # Regression: smart-tier chats spent one of the 3 weekly smart requests per
    # researched university, so the deck's second or third research got a 429.
    create = _Recorder(SimpleNamespace(id=CHAT_ID))
    rename = _Recorder()
    adapter = AdmissionUniChatsAdapter(
        SimpleNamespace(create_chat=create, rename_chat=rename)
    )
    actor = Actor(
        user_id=UUID("00000000-0000-7000-8000-000000000002"), roles=frozenset()
    )

    chat_id = await adapter.start(actor, "Harvard University")

    assert chat_id == CHAT_ID
    assert create.calls == [
        {"actor": actor, "assistant": Assistant.STUDENT, "tier": ChatTier.FAST}
    ]
    assert rename.calls[0]["title"] == "Harvard University"
