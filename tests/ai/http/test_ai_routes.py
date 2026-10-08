"""HTTP: /v1/ai/* follows the API contract (paths, fields, status codes, errors)."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.ai import ROUTERS
from app.shared.actor import Actor
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest
from httpx import AsyncClient

CARDS = {"title": "Cells", "cards": [{"front": "Q", "back": "A"}]}


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor the next request runs as."""
    return {}


@pytest.fixture
async def api(
    make_harness: HarnessFactory, http_client: Any, current: dict[str, Actor]
) -> tuple[AiHarness, AsyncClient]:
    """The harness and a client whose requests run as `current["actor"]`."""
    h = make_harness()
    current["actor"] = h.student
    client = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, ai=h.services
    )
    return h, client


async def create_chat(
    client: AsyncClient, assistant: str = "student"
) -> dict[str, Any]:
    """POST /v1/ai/chats."""
    response = await client.post("/v1/ai/chats", json={"assistant": assistant})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_chat_crud_follows_the_contract(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI-1: create, list, open, rename, delete."""
    _, client = api

    chat = await create_chat(client)
    listed = (await client.get("/v1/ai/chats", params={"assistant": "student"})).json()
    opened = (await client.get(f"/v1/ai/chats/{chat['id']}")).json()
    renamed = await client.patch(
        f"/v1/ai/chats/{chat['id']}", json={"title": "Biology"}
    )
    deleted = await client.delete(f"/v1/ai/chats/{chat['id']}")
    missing = await client.get(f"/v1/ai/chats/{chat['id']}")

    assert set(chat) == {
        "id",
        "assistant",
        "title",
        "last_message_at",
        "pending_approvals",
    }
    assert chat["assistant"] == "student" and chat["pending_approvals"] == 0
    assert listed == {"items": [chat], "next_cursor": None}
    assert opened == {**chat, "messages": [], "shared": False}
    assert renamed.json()["title"] == "Biology"
    assert deleted.status_code == 204 and deleted.content == b""
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["type"] == "ai/chat-not-found"


async def test_sending_a_message_returns_a_turn_result(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """UF-WEB-19: TurnResult = chat, new_messages, status, usage."""
    h, client = api
    chat = await create_chat(client)
    h.llm.push(text_reply("Hello!"))

    response = await client.post(
        f"/v1/ai/chats/{chat['id']}/messages", json={"text": "Hi there", "file_ids": []}
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"chat", "new_messages", "status", "usage"}
    assert body["status"] == "done" and body["chat"]["title"] == "Hi there"
    user, answer = body["new_messages"]
    assert set(user) == {"seq", "role", "text", "file_ids", "tool_calls", "created_at"}
    assert (user["seq"], user["role"], answer["text"]) == (1, "user", "Hello!")
    assert body["usage"]["session"]["used"] == 120
    assert body["usage"]["day"]["limit"] == 600_000
    assert body["usage"]["day"]["resets_at"].endswith("Z")


async def test_approval_over_http_and_the_tool_call_view(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """UF-WEB-20: the card, Approve once, then a conflict."""
    h, client = api
    chat = await create_chat(client)
    h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
    proposed = (
        await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "cards"})
    ).json()
    call = proposed["new_messages"][-1]["tool_calls"][0]
    url = f"/v1/ai/chats/{chat['id']}/tool-calls/{call['id']}"
    h.llm.push(text_reply("Created."))

    approved = await client.post(f"{url}/approve")
    again = await client.post(f"{url}/approve")

    assert (
        proposed["status"] == "awaiting_approval"
        and proposed["chat"]["pending_approvals"] == 1
    )
    assert set(call) == {
        *("id", "tool", "access", "status", "note"),
        *("preview", "reject_reason", "expires_at"),
    }
    assert call["status"] == "pending_approval" and call["access"] == "write"
    assert set(call["preview"]) == {"title", "fields", "items"}
    assert call["preview"]["fields"] == [
        {"label": "Title", "value": "Cells", "sensitive": False}
    ]
    assert approved.status_code == 200 and approved.json()["status"] == "done"
    assert again.status_code == 409
    assert again.json()["type"] == "ai/tool-call-not-pending"
    assert len(h.flashcards.create_calls) == 1


async def test_reject_takes_an_optional_reason(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI-3: reject works with and without a body."""
    h, client = api
    chat = await create_chat(client)
    ids = []
    for _ in range(2):
        h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
        sent = await client.post(
            f"/v1/ai/chats/{chat['id']}/messages", json={"text": "c"}
        )
        ids.append(sent.json()["new_messages"][-1]["tool_calls"][0]["id"])
        if len(ids) == 1:
            with_reason = await client.post(
                f"/v1/ai/chats/{chat['id']}/tool-calls/{ids[0]}/reject",
                json={"reason": "too long"},
            )
    without_body = await client.post(
        f"/v1/ai/chats/{chat['id']}/tool-calls/{ids[1]}/reject"
    )

    assert (
        with_reason.json()["new_messages"][0]["tool_calls"][0]["reject_reason"]
        == "too long"
    )
    assert without_body.status_code == 200
    assert (
        without_body.json()["new_messages"][0]["tool_calls"][0]["reject_reason"] is None
    )


async def test_expired_card_is_gone(api: tuple[AiHarness, AsyncClient]) -> None:
    """AI-11: 410 after 24 hours."""
    h, client = api
    chat = await create_chat(client)
    h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
    sent = await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "c"})
    call_id = sent.json()["new_messages"][-1]["tool_calls"][0]["id"]
    h.clock.advance(hours=25)

    response = await client.post(
        f"/v1/ai/chats/{chat['id']}/tool-calls/{call_id}/approve"
    )

    assert (
        response.status_code == 410
        and response.json()["type"] == "ai/tool-call-expired"
    )


async def test_usage_and_limit_errors(api: tuple[AiHarness, AsyncClient]) -> None:
    """AI-8: GET /usage, and 429 ai/limit-reached with the reset time."""
    h, client = api
    usage = await client.get("/v1/ai/usage")
    wrong = await client.get("/v1/ai/usage", params={"assistant": "admin"})
    chat = await create_chat(client)
    await h.services.send_message.continue_turn.budget.add(h.student.user_id, 590_000)
    blocked = await client.post(
        f"/v1/ai/chats/{chat['id']}/messages", json={"text": "hi"}
    )

    assert usage.json() == {
        "session": {"used": 0, "limit": 200_000, "resets_at": None},
        "day": {"used": 0, "limit": 600_000, "resets_at": "2026-10-06T19:00:00Z"},
    }
    assert wrong.status_code == 403 and wrong.json()["type"] == "ai/wrong-assistant"
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["type"] == "ai/limit-reached" and body["params"]["scope"] in {
        "session",
        "day",
    }


async def test_roles_and_validation(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI-1: roles pick the assistant; bad bodies are 422."""
    h, client = api

    student_admin_chat = await client.post("/v1/ai/chats", json={"assistant": "admin"})
    empty = await client.post(
        f"/v1/ai/chats/{(await create_chat(client))['id']}/messages", json={"text": ""}
    )
    current["actor"] = h.admin
    admin_chat = await client.post("/v1/ai/chats", json={"assistant": "admin"})
    admin_list = await client.get("/v1/ai/chats")

    assert student_admin_chat.status_code == 403
    assert (
        empty.status_code == 422 and empty.json()["type"] == "common/request-validation"
    )
    assert admin_chat.status_code == 200 and admin_chat.json()["assistant"] == "admin"
    assert [c["assistant"] for c in admin_list.json()["items"]] == ["admin"]
