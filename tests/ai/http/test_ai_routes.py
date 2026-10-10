"""HTTP: /v1/ai/* follows the API contract (paths, fields, status codes, errors)."""

from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.ai import ROUTERS
from app.shared.actor import Actor
from tests.ai.author_support import arrange
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
        "tier",
        "course_id",
    }
    assert chat["assistant"] == "student" and chat["pending_approvals"] == 0
    assert chat["tier"] == "fast"
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
    assert set(user) == {
        *("seq", "role", "text", "file_ids", "tool_calls", "created_at"),
        *("feedback", "web"),
    }
    assert user["web"] == [] and answer["web"] == []
    assert (user["seq"], user["role"], answer["text"]) == (1, "user", "Hello!")
    assert user["feedback"] is None and answer["feedback"] is None
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
        *("preview", "reject_reason", "expires_at", "document"),
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


async def test_regenerate_returns_a_turn_result_and_checks_the_state(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI-2, AI-11: 200 TurnResult; 404 for others; 409 if empty or a card waits."""
    h, client = api
    chat = await create_chat(client)
    url = f"/v1/ai/chats/{chat['id']}/regenerate"
    empty = await client.post(url)
    h.llm.push(text_reply("First"))
    await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "Hi"})
    h.llm.push(text_reply("Second"))

    response = await client.post(url)

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"chat", "new_messages", "status", "usage"}
    assert body["status"] == "done"
    assert [(m["seq"], m["role"], m["text"]) for m in body["new_messages"]] == [
        (2, "assistant", "Second")
    ]
    assert empty.status_code == 409
    assert empty.json()["type"] == "ai/nothing-to-regenerate"

    h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
    await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "cards"})
    waiting = await client.post(url)
    current["actor"] = h.other_student
    stranger = await client.post(url)

    assert waiting.status_code == 409
    assert waiting.json()["type"] == "ai/approval-pending"
    assert stranger.status_code == 404
    assert stranger.json()["type"] == "ai/chat-not-found"


async def test_regenerate_over_the_limit_is_429(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI-8: the same ai/limit-reached problem as sending a message."""
    h, client = api
    chat = await create_chat(client)
    h.llm.push(text_reply("Hello"))
    await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "Hi"})
    await h.services.send_message.continue_turn.budget.add(h.student.user_id, 590_000)

    response = await client.post(f"/v1/ai/chats/{chat['id']}/regenerate")

    assert response.status_code == 429
    assert response.json()["type"] == "ai/limit-reached"
    assert response.json()["params"]["scope"] in {"session", "day"}


async def test_feedback_is_204_and_shows_in_the_chat(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI-1: set, replace, and the value comes back as `feedback` of the message."""
    h, client = api
    chat = await create_chat(client)
    url = f"/v1/ai/chats/{chat['id']}/messages/2/feedback"
    await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "Hi"})

    up = await client.post(url, json={"rating": "up"})
    again = await client.post(url, json={"rating": "up"})
    after_up = (await client.get(f"/v1/ai/chats/{chat['id']}")).json()
    down = await client.post(url, json={"rating": "down", "comment": "x" * 500})
    after_down = (await client.get(f"/v1/ai/chats/{chat['id']}")).json()

    assert (up.status_code, up.content) == (204, b"")
    assert again.status_code == 204 and down.status_code == 204
    assert [m["feedback"] for m in after_up["messages"]] == [None, "up"]
    assert [m["feedback"] for m in after_down["messages"]] == [None, "down"]
    stored = h.store.chat_messages(UUID(chat["id"]))[1]
    assert stored.feedback_comment == "x" * 500


async def test_feedback_errors(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI-1: 422 for bad bodies and user messages, 404 for unknown seq or owner."""
    h, client = api
    chat = await create_chat(client)
    await client.post(f"/v1/ai/chats/{chat['id']}/messages", json={"text": "Hi"})
    base = f"/v1/ai/chats/{chat['id']}/messages"

    on_user = await client.post(f"{base}/1/feedback", json={"rating": "up"})
    missing_seq = await client.post(f"{base}/9/feedback", json={"rating": "up"})
    seq_zero = await client.post(f"{base}/0/feedback", json={"rating": "up"})
    bad_rating = await client.post(f"{base}/2/feedback", json={"rating": "meh"})
    no_rating = await client.post(f"{base}/2/feedback", json={})
    null_rating = await client.post(f"{base}/2/feedback", json={"rating": None})
    long_comment = await client.post(
        f"{base}/2/feedback", json={"rating": "up", "comment": "x" * 501}
    )
    current["actor"] = h.other_student
    stranger = await client.post(f"{base}/2/feedback", json={"rating": "up"})

    assert on_user.status_code == 422
    assert on_user.json()["type"] == "ai/feedback-not-allowed"
    assert missing_seq.status_code == 404
    assert missing_seq.json()["type"] == "ai/message-not-found"
    for refused in (seq_zero, bad_rating, no_rating, null_rating, long_comment):
        assert refused.status_code == 422
        assert refused.json()["type"] == "common/request-validation"
    assert stranger.status_code == 404
    assert stranger.json()["type"] == "ai/chat-not-found"


async def test_chat_search_by_title(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI-1: `q` filters by title, keeps `assistant` and the cursor, 1..100 chars."""
    h, client = api
    for title in ("Biology notes", "Algebra", "biology exam"):
        h.clock.advance(minutes=1)
        chat = await create_chat(client)
        await client.patch(f"/v1/ai/chats/{chat['id']}", json={"title": title})

    found = await client.get("/v1/ai/chats", params={"q": "BIO"})
    page = await client.get("/v1/ai/chats", params={"q": "bio", "limit": 1})
    rest = await client.get(
        "/v1/ai/chats",
        params={"q": "bio", "limit": 1, "cursor": page.json()["next_cursor"]},
    )
    wildcard = await client.get("/v1/ai/chats", params={"q": "%"})
    wrong = await client.get("/v1/ai/chats", params={"q": "bio", "assistant": "admin"})
    longest = await client.get("/v1/ai/chats", params={"q": "b" * 100})
    empty = await client.get("/v1/ai/chats", params={"q": ""})
    too_long = await client.get("/v1/ai/chats", params={"q": "b" * 101})
    current["actor"] = h.admin
    admin = await client.get("/v1/ai/chats", params={"q": "bio"})

    assert [c["title"] for c in found.json()["items"]] == [
        "biology exam",
        "Biology notes",
    ]
    assert [c["title"] for c in page.json()["items"]] == ["biology exam"]
    assert [c["title"] for c in rest.json()["items"]] == ["Biology notes"]
    assert rest.json()["next_cursor"] is None
    assert wildcard.json()["items"] == []
    assert wrong.status_code == 403
    assert longest.status_code == 200 and longest.json()["items"] == []
    assert empty.status_code == 422 and too_long.status_code == 422
    assert admin.json()["items"] == []


async def test_a_chat_is_created_on_a_tier(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI-13: `tier` is optional and fast by default; smart is shown everywhere."""
    h, client = api

    plain = await create_chat(client)
    explicit = await client.post(
        "/v1/ai/chats", json={"assistant": "student", "tier": "fast"}
    )
    no_tier = await client.post(
        "/v1/ai/chats", json={"assistant": "student", "tier": None}
    )
    smart = await client.post(
        "/v1/ai/chats", json={"assistant": "student", "tier": "smart"}
    )
    bad = await client.post(
        "/v1/ai/chats", json={"assistant": "student", "tier": "turbo"}
    )
    opened = (await client.get(f"/v1/ai/chats/{smart.json()['id']}")).json()
    listed = (await client.get("/v1/ai/chats", params={"limit": 1})).json()
    h.llm.push(text_reply("Hello"))
    sent = await client.post(
        f"/v1/ai/chats/{smart.json()['id']}/messages", json={"text": "Hi"}
    )
    current["actor"] = h.admin
    admin = await client.post(
        "/v1/ai/chats", json={"assistant": "admin", "tier": "smart"}
    )

    assert plain["tier"] == "fast" and explicit.json()["tier"] == "fast"
    assert no_tier.json()["tier"] == "fast"
    assert smart.status_code == 200 and smart.json()["tier"] == "smart"
    assert bad.status_code == 422
    assert bad.json()["type"] == "common/request-validation"
    assert opened["tier"] == "smart" and listed["items"][0]["tier"] == "smart"
    assert sent.json()["chat"]["tier"] == "smart"
    assert sent.json()["usage"]["session"]["used"] == 480
    assert h.llm.requests[-1]["model"] == "anthropic/claude-sonnet-5.5"
    assert admin.json()["tier"] == "fast"


async def test_course_author_chats_over_http(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """lms_author: course_id is required (422), editors only (403), per course."""
    h, client = api
    author = arrange(h)
    current["actor"] = h.teacher
    body = {"assistant": "lms_author", "course_id": str(author.course.id)}

    missing = await client.post("/v1/ai/chats", json={"assistant": "lms_author"})
    created = await client.post("/v1/ai/chats", json=body)
    listed = await client.get(
        "/v1/ai/chats",
        params={"assistant": "lms_author", "course_id": str(author.course.id)},
    )
    usage = await client.get(
        "/v1/ai/usage",
        params={"assistant": "lms_author", "course_id": str(author.course.id)},
    )
    current["actor"] = h.student
    stranger = await client.post("/v1/ai/chats", json=body)

    assert (missing.status_code, missing.json()["type"]) == (422, "ai/course-required")
    assert created.status_code == 200
    assert created.json()["course_id"] == str(author.course.id)
    assert [c["id"] for c in listed.json()["items"]] == [created.json()["id"]]
    assert usage.json()["day"]["limit"] == h.settings.limits.lms_ai_daily_tokens
    assert (stranger.status_code, stranger.json()["type"]) == (
        403,
        "ai/wrong-assistant",
    )
