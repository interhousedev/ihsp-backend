"""The make_document tool stores the file for the user and returns a card."""

import json
from typing import Any

from app.modules.notebooks.application.export.render import DocumentExporter
from app.shared.contracts.files import FilePurpose, FileScope
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply


async def test_make_document_stores_an_owned_file_and_shows_a_card(
    h: AiHarness,
) -> None:
    """The file belongs to the student, uses the chat-upload purpose and has a card."""
    h.services.bindings.documents = DocumentExporter()
    chat = await h.new_chat()
    args: dict[str, Any] = {"kind": "docx", "title": "Cells", "content": "# Cells\n- a"}
    h.llm.push(tool_reply(("make_document", args)), text_reply("Here it is."))

    result = await h.say(chat.id, "make a doc")

    call = result.new_messages[1].tool_calls[0]
    assert call.status == "done" and call.document is not None
    assert call.document.name == "Cells.docx" and call.document.kind == "docx"
    ref = h.files.files[call.document.file_id]
    assert ref.owner_id == h.student.user_id
    assert ref.purpose is FilePurpose.AI_UPLOAD and ref.scope is FileScope.STUDENT
    assert h.files.stored[ref.id][:2] == b"PK"
    sent = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    assert sent["untrusted_data"]["file_id"] == str(ref.id)


async def test_make_document_without_the_renderer_fails_softly(h: AiHarness) -> None:
    """No renderer bound: the model gets a failure, no file is stored."""
    chat = await h.new_chat()
    args = {"kind": "xlsx", "title": "T", "content": "a,b"}
    h.llm.push(tool_reply(("make_document", args)), text_reply("Sorry."))

    result = await h.say(chat.id, "table")

    assert result.new_messages[1].tool_calls[0].status == "failed"
    assert not h.files.stored
