"""AI chats: slash commands are parsed and mapped on the agent side."""

from app.modules.ai.domain.chat import MessageRole
from app.shared.slash_commands import (
    NAMES,
    UnknownCommandError,
    expand,
    parse_typed,
    resolve,
    stored_text,
)
from tests.ai.conftest import AiHarness

import pytest

REQUESTED = (
    "goal cards quiz summary mindmap slides report table explain translate help"
).split()


def test_the_registry_has_the_documented_commands() -> None:
    assert list(NAMES) == REQUESTED


def test_typed_text_is_parsed_into_command_and_args() -> None:
    parsed = parse_typed("/Cards  photosynthesis basics ")
    assert parsed is not None
    assert (parsed.command, parsed.args) == ("cards", "photosynthesis basics")
    bare = parse_typed("/help")
    assert bare is not None and (bare.command, bare.args) == ("help", "")


@pytest.mark.parametrize("text", ["hello /cards", "/usr/bin", "/ 5", "", "2/3"])
def test_ordinary_text_with_a_slash_is_not_a_command(text: str) -> None:
    assert parse_typed(text) is None
    assert stored_text(None, "", text) == text
    assert expand(text) == text


def test_a_command_is_stored_in_its_short_form() -> None:
    assert stored_text("cards", " mitosis ", "") == "/cards mitosis"
    assert stored_text("/quiz", "", "ignored") == "/quiz"
    assert stored_text(None, "", "/summary cell cycle") == "/summary cell cycle"


def test_every_command_expands_to_a_prompt_with_the_args() -> None:
    for name in NAMES:
        prompt = expand(f"/{name} the Krebs cycle")
        assert not prompt.startswith("/") and "Krebs cycle" in prompt
    assert "/mindmap" in expand("/help")


def test_a_command_without_args_asks_for_the_topic() -> None:
    assert "ask the user" in expand("/cards")
    assert "nothing yet" not in expand("/help")


def test_unknown_commands_are_refused_with_the_known_ones() -> None:
    with pytest.raises(UnknownCommandError) as raised:
        resolve("flarp")
    assert raised.value.code == "ai/unknown-command"
    assert raised.value.params["command"] == "flarp"
    assert "/cards" in raised.value.params["known"]
    with pytest.raises(UnknownCommandError):
        stored_text(None, "", "/flarp now")


async def test_the_model_gets_the_prompt_and_the_chat_keeps_the_command(
    h: AiHarness,
) -> None:
    chat = await h.new_chat()

    await h.services.send_message.execute(
        actor=h.student,
        chat_id=chat.id,
        text="",
        file_ids=[],
        command="cards",
        args="photosynthesis",
    )

    stored = h.store.chat_messages(chat.id)[0]
    assert stored.role is MessageRole.USER and stored.text == "/cards photosynthesis"
    sent = h.llm.requests[0]["messages"]
    user = next(m for m in sent if m["role"] == "user")
    assert "flash cards" in user["content"] and "photosynthesis" in user["content"]


async def test_an_unknown_command_stores_nothing(h: AiHarness) -> None:
    chat = await h.new_chat()

    with pytest.raises(UnknownCommandError):
        await h.say(chat.id, "/flarp topic")

    assert h.store.chat_messages(chat.id) == [] and h.llm.requests == []
