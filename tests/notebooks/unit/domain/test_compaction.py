"""AI-EFF-2/3: which turns go in full, which are summarised, when to re-summarise."""

from app.modules.notebooks.domain.compaction import (
    REFRESH_EVERY,
    SUMMARY_HEAD,
    CompactSummary,
    needs_refresh,
    plan,
    render_transcript,
    split_history,
    summary_note,
)
from app.modules.notebooks.domain.entities import MessageContent, NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.shared.ids import new_id
from tests.notebooks.unit.domain.pack_builder import NOW

USER_ID = new_id()
NOTEBOOK_ID = new_id()


def message(seq: int, text: str = "") -> NotebookMessage:
    return NotebookMessage(
        id=new_id(),
        notebook_id=NOTEBOOK_ID,
        user_id=USER_ID,
        seq=seq,
        role=MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
        content=MessageContent(text=text or f"message {seq}"),
        created_at=NOW,
    )


def chat(count: int) -> list[NotebookMessage]:
    return [message(seq) for seq in range(1, count + 1)]


def test_the_last_n_messages_go_in_full() -> None:
    """AI-EFF-3: the history limit cuts the thread; the rest is older."""
    history = chat(10)

    older, window = split_history(history, limit=4, max_chars=10_000)

    assert [m.seq for m in window] == [7, 8, 9, 10]
    assert [m.seq for m in older] == [1, 2, 3, 4, 5, 6]


def test_a_short_thread_has_nothing_older() -> None:
    """AI-EFF-3: below the limit nothing is summarised."""
    older, window = split_history(chat(3), limit=20, max_chars=10_000)

    assert older == [] and [m.seq for m in window] == [1, 2, 3]


def test_the_window_starts_with_a_question() -> None:
    """AI-EFF-3: an odd limit does not start the window with an answer."""
    older, window = split_history(chat(10), limit=3, max_chars=10_000)

    assert window[0].role is MessageRole.USER
    assert [m.seq for m in window] == [9, 10]
    assert older[-1].seq == 8


def test_oversized_turns_move_to_the_summary() -> None:
    """AI-EFF-2: when the window is over the character budget, old turns move out."""
    history = [message(seq, "x" * 1000) for seq in range(1, 9)]

    older, window = split_history(history, limit=8, max_chars=2500)

    assert len(window) == 2 and [m.seq for m in window] == [7, 8]
    assert [m.seq for m in older] == [1, 2, 3, 4, 5, 6]


def test_a_cached_summary_is_reused_until_enough_turns_fall_out() -> None:
    """AI-EFF-2: the stored summary is kept; only the gap is new."""
    older = chat(12)
    stored = CompactSummary("s", upto_seq=10, upto_id=older[9].id)

    base, fresh = plan(stored, older)

    assert base == stored
    assert [m.seq for m in fresh] == [11, 12]
    assert not needs_refresh(base, fresh)
    assert needs_refresh(base, chat(REFRESH_EVERY))


def test_a_summary_of_another_thread_is_ignored() -> None:
    """AI-EFF-2: a cleared chat restarts seq numbers; the id check catches it."""
    older = chat(6)
    stale = CompactSummary("old", upto_seq=4, upto_id=new_id())

    base, fresh = plan(stale, older)

    assert base is None and len(fresh) == 6
    assert needs_refresh(base, fresh)


def test_the_transcript_carries_the_previous_summary_and_cuts_long_texts() -> None:
    """AI-EFF-2: incremental: earlier summary plus the new turns only."""
    text = render_transcript("earlier facts", [message(1, "y" * 5000)])

    assert "Earlier summary: earlier facts" in text
    assert "user: " in text
    assert len(text) < 3000


def test_the_summary_note_is_marked_as_context() -> None:
    """AI-EFF-2: the model sees the summary as context, not as a question."""
    assert summary_note(None) is None
    note = summary_note("facts")
    assert note is not None and note.startswith(SUMMARY_HEAD) and "facts" in note
