"""NB-12: the chat history sent to the model (§ 3.3.3)."""

from app.modules.notebooks.domain.entities import MessageContent, NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.history import history_messages
from app.shared.ids import new_id
from tests.notebooks.unit.domain.pack_builder import NOW

USER_ID = new_id()
NOTEBOOK_ID = new_id()


def message(
    seq: int,
    role: MessageRole,
    text: str,
    *,
    followups: list[str] | None = None,
    stopped: bool = False,
) -> NotebookMessage:
    return NotebookMessage(
        id=new_id(),
        notebook_id=NOTEBOOK_ID,
        user_id=USER_ID,
        seq=seq,
        role=role,
        content=MessageContent(text=text, followups=followups or []),
        created_at=NOW,
        stopped=stopped,
    )


def chat(count: int) -> list[NotebookMessage]:
    return [
        message(
            seq,
            MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
            f"message {seq}",
        )
        for seq in range(1, count + 1)
    ]


def test_history_returns_role_and_content_pairs_in_order() -> None:
    history = history_messages(chat(3))

    assert history == [
        {"role": "user", "content": "message 1"},
        {"role": "assistant", "content": "message 2"},
        {"role": "user", "content": "message 3"},
    ]


def test_history_keeps_the_last_twelve_messages_by_default() -> None:
    history = history_messages(chat(20))

    assert [m["content"] for m in history] == [f"message {n}" for n in range(9, 21)]


def test_history_honours_a_custom_limit() -> None:
    history = history_messages(chat(10), limit=4)

    assert [m["content"] for m in history] == [f"message {n}" for n in range(7, 11)]


def test_history_with_a_zero_limit_is_empty() -> None:
    assert history_messages(chat(5), limit=0) == []


def test_history_of_an_empty_chat_is_empty() -> None:
    assert history_messages([]) == []


def test_history_turns_assistant_chips_into_bracketed_numbers() -> None:
    answer = message(2, MessageRole.ASSISTANT, "Light ⟦1⟧ becomes sugar ⟦2,3⟧.")

    history = history_messages([answer])

    assert history == [
        {"role": "assistant", "content": "Light [1] becomes sugar [2][3]."}
    ]


def test_history_does_not_rewrite_user_text() -> None:
    question = message(1, MessageRole.USER, "What is ⟦1⟧?")

    assert history_messages([question])[0]["content"] == "What is ⟦1⟧?"


def test_history_leaves_followups_out() -> None:
    answer = message(2, MessageRole.ASSISTANT, "Answer.", followups=["Why?", "How?"])

    history = history_messages([answer])

    assert history == [{"role": "assistant", "content": "Answer."}]


def test_history_includes_stopped_answers() -> None:
    stopped = message(2, MessageRole.ASSISTANT, "Half an answ", stopped=True)

    assert history_messages([stopped]) == [
        {"role": "assistant", "content": "Half an answ"}
    ]


def test_history_skips_messages_without_text() -> None:
    empty = message(2, MessageRole.ASSISTANT, "  ", stopped=True)

    history = history_messages([message(1, MessageRole.USER, "Hi"), empty])

    assert history == [{"role": "user", "content": "Hi"}]
