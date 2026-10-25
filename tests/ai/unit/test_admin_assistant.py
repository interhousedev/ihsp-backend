"""AI-6, AI-11, ADM-15, UF-ADM-12: the Administration assistant."""

import json
from typing import Any

from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.assistant import Assistant
from app.shared.base_error import ConflictError
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply


class SlotTaken(ConflictError):
    """The backend refuses a timetable change."""

    code = "timetable/conflict"


async def test_admin_read_tool_is_forwarded_as_the_admin(h: AiHarness) -> None:
    """AI-6: read tools call the backend with the actor and plain JSON arguments."""
    h.admin_backend.results["list_groups"] = {"groups": [{"name": "2TN2"}]}
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    h.llm.push(
        tool_reply(("list_groups", {"status": "active"})), text_reply("One group.")
    )

    result = await h.say(chat.id, "which groups?", actor=h.admin)

    tool, arguments, actor = h.admin_backend.calls[0]
    assert (tool, arguments, actor.user_id) == (
        "list_groups",
        {"status": "active"},
        h.admin.user_id,
    )
    assert result.status is TurnStatus.DONE
    seen = json.loads(h.llm.requests[1]["messages"][-1]["content"])
    assert seen == {"untrusted_data": {"groups": [{"name": "2TN2"}]}}
    assert h.llm.requests[0]["tools"][0]["function"]["name"] == "search_users"


async def test_admin_write_shows_sensitive_fields_and_waits(h: AiHarness) -> None:
    """AI-11: changes to curator and head student are highlighted; nothing runs yet."""
    teacher_id = new_id()
    group_id = new_id()
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    h.llm.push(
        tool_reply(
            ("update_group", {"group_id": str(group_id), "curator_id": str(teacher_id)})
        )
    )

    result = await h.say(chat.id, "make them curator", actor=h.admin)

    call = result.new_messages[-1].tool_calls[0]
    assert result.status is TurnStatus.AWAITING_APPROVAL
    assert call.preview is not None and call.preview.title == "Change a group"
    fields = {f.label: f for f in call.preview.fields}
    assert fields["Curator"].sensitive and not fields["Group"].sensitive
    assert h.admin_backend.calls == []


async def test_approved_admin_write_calls_the_backend_and_is_audited(
    h: AiHarness,
) -> None:
    """UF-ADM-12: the approved change is made by the backend as the admin."""
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    args = {"last_name": "Aliyev", "first_name": "Sardor", "email": "s@school.uz"}
    h.llm.push(tool_reply(("create_teacher", args)))
    proposed = await h.say(chat.id, "add teacher", actor=h.admin)
    call_id = proposed.new_messages[-1].tool_calls[0].id
    h.llm.push(text_reply("Created."))

    result = await h.services.approve_tool_call.execute(
        actor=h.admin, chat_id=chat.id, call_id=call_id
    )

    assert h.admin_backend.calls[0][:2] == ("create_teacher", args)
    assert result.new_messages[0].tool_calls[0].status == "done"
    audit = h.store.audits[-1]
    assert audit.type == "ai.write_approved" and audit.actor_id == h.admin.user_id
    preview = proposed.new_messages[-1].tool_calls[0].preview
    assert preview is not None
    assert next(f for f in preview.fields if f.value == "s@school.uz").sensitive


async def test_a_backend_conflict_is_reported_to_the_assistant(h: AiHarness) -> None:
    """UF-ADM-12 3d: a conflict at approval time fails the call; the model is told."""
    h.admin_backend.fail_with = SlotTaken(support_details="room 204 is busy")
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    entry: dict[str, Any] = {"entry_id": str(new_id()), "period": 4}
    h.llm.push(tool_reply(("update_timetable_entry", entry)))
    proposed = await h.say(chat.id, "move to period 4", actor=h.admin)
    call_id = proposed.new_messages[-1].tool_calls[0].id
    h.llm.push(text_reply("Room 204 is busy."))

    result = await h.services.approve_tool_call.execute(
        actor=h.admin, chat_id=chat.id, call_id=call_id
    )

    assert result.new_messages[0].tool_calls[0].status == "failed"
    error = json.loads(h.llm.requests[-1]["messages"][-1]["content"])["error"]
    assert "timetable/conflict" in error and "room 204 is busy" in error


async def test_broadcasts_are_only_drafts(h: AiHarness) -> None:
    """AI-6: create_broadcast_draft is the only broadcast tool."""
    chat = await h.new_chat(assistant=Assistant.ADMIN)
    h.llm.push(text_reply("ok"))
    await h.say(chat.id, "hi", actor=h.admin)

    names = {t["function"]["name"] for t in h.llm.requests[0]["tools"]}

    assert "create_broadcast_draft" in names
    assert not {n for n in names if "send" in n or n.startswith("delete_broadcast")}
    assert {"get_marks", "read_file"}.isdisjoint(names)


async def test_admin_chats_cannot_be_shared(h: AiHarness) -> None:
    """AI-12: chat_for_share gives nothing for Administration chats."""
    chat = await h.new_chat(assistant=Assistant.ADMIN)

    assert await h.services.public.chat_for_share(chat.id, None) is None
