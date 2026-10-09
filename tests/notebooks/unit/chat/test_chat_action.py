"""NB-8, NB-6: the Studio output a chat answer proposes (P2, § 3.3)."""

import json
from datetime import date

from app.modules.notebooks.domain.artifacts.registry import supported_kinds
from app.modules.notebooks.domain.chat_action import split_action
from app.modules.notebooks.domain.enums import ChatLength, ChatStyle, ReportFormat
from app.modules.notebooks.domain.prompts.chat import chat_system_prompt
from app.modules.notebooks.wiring_chat import ChatServices
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    collect,
    names,
    notebook_with_source,
    streamed_text,
    thread,
)

import pytest

QUIZ = (
    '<action>{"kind": "quiz", "options": {"count": "more"}, '
    '"prompt": "Calvin cycle"}</action>'
)
FOLLOWUPS = '<followups>["Another?"]</followups>'


def action_of(payload: object) -> dict[str, object] | None:
    return split_action(f"x <action>{json.dumps(payload)}</action>")[1]


# - - - the prompt - - -


def test_the_system_prompt_teaches_the_action_tag_before_the_date_line() -> None:
    """NB-8: rule 8 names every Studio kind and report format the Studio can run."""
    text = chat_system_prompt(
        language="en",
        style=ChatStyle.DEFAULT,
        custom_prompt=None,
        length=ChatLength.DEFAULT,
        today=date(2026, 10, 8),
    )

    rule = next(line for line in text.splitlines() if line.startswith("8. "))
    assert "explicitly asks" in rule
    assert "before <followups>, <action>" in text
    for kind in supported_kinds():
        if not kind.is_course_kind:  # the chat never proposes course outputs
            assert kind.value in text
    for report_format in ReportFormat:
        assert report_format.value in text
    assert text.splitlines()[-1] == "Today is 2026-10-08 (Asia/Tashkent)."


# - - - split_action - - -


def test_a_valid_action_is_read_and_its_tag_is_cut() -> None:
    """NB-8: kind, options with defaults filled, the focus prompt."""
    text, action = split_action(f"Done.\n{QUIZ}\n{FOLLOWUPS}")

    assert text == f"Done.\n{FOLLOWUPS}"
    assert action is not None
    assert action["kind"] == "quiz" and action["prompt"] == "Calvin cycle"
    assert action["options"]["count"] == "more"
    assert action["options"]["difficulty"] == "medium"


def test_text_without_a_tag_is_returned_untouched() -> None:
    """NB-8: no tag, no action."""
    assert split_action("Plain *text*.\n") == ("Plain *text*.\n", None)


def test_a_tag_at_the_end_is_removed_with_the_space_before_it() -> None:
    """NB-8: the sentence stays clean."""
    text, action = split_action(f"Sure, here is a quiz.  \n{QUIZ}")

    assert text == "Sure, here is a quiz."
    assert action is not None and action["kind"] == "quiz"


def test_the_tag_is_case_insensitive_and_json_may_sit_in_a_code_fence() -> None:
    """NB-8: tolerant parsing."""
    raw = '<ACTION>```json\n{"kind": "mind_map"}\n```</ACTION>'

    text, action = split_action(raw)

    assert text == ""
    assert action == {
        "kind": "mind_map",
        "options": {"detail": "overview"},
        "prompt": None,
    }


def test_a_report_keeps_its_format() -> None:
    """NB-8: report options are validated by the report handler."""
    action = action_of({"kind": "report", "options": {"format": "conspect"}})

    assert action is not None
    assert action["options"]["format"] == "conspect"  # type: ignore[index]
    assert action["options"]["detail"] == "standard"  # type: ignore[index]


def test_a_custom_report_needs_a_prompt() -> None:
    """NB-8: the task block rejects a custom report without a task."""
    bare = {"kind": "report", "options": {"format": "custom"}}

    assert action_of(bare) is None
    assert action_of({**bare, "prompt": "Compare ATP and NADPH"}) is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "poster"},
        {"kind": "audio_overview"},
        {"kind": 7},
        {"options": {}},
        {"kind": "report"},
        {"kind": "report", "options": {"format": "novel"}},
        {"kind": "quiz", "options": {"count": "huge"}},
        {"kind": "quiz", "options": []},
        ["quiz"],
        "quiz",
        None,
    ],
)
def test_an_invalid_or_unsupported_proposal_gives_no_action(payload: object) -> None:
    """NB-8: unknown kinds, audio (P3) and bad options are dropped."""
    assert action_of(payload) is None


@pytest.mark.parametrize(
    "raw",
    ["<action>{not json}</action>", "<action></action>", "<action>", "<action foo"],
)
def test_broken_tags_give_no_action_but_are_still_cut(raw: str) -> None:
    """NB-8: the tag never stays in the text."""
    text, action = split_action(f"Hi. {raw}")

    assert text == "Hi."
    assert action is None


def test_an_unterminated_tag_runs_to_the_followups() -> None:
    """NB-8: a model that forgets `</action>` still gives a clean split."""
    text, action = split_action(f'Hi.\n<action>{{"kind": "quiz"}}\n{FOLLOWUPS}')

    assert text == f"Hi.\n{FOLLOWUPS}"
    assert action is not None and action["kind"] == "quiz"


def test_followups_before_the_action_are_left_for_their_own_parser() -> None:
    """NB-8: the order of the two tags does not matter."""
    text, action = split_action(f'Hi.\n{FOLLOWUPS}\n<action>{{"kind":"quiz"}}</action>')

    assert text == f"Hi.\n{FOLLOWUPS}"
    assert action is not None and action["kind"] == "quiz"


def test_source_ids_in_the_options_are_dropped() -> None:
    """NB-5: the model knows no ids; the student's selection decides."""
    options = {"source_ids": ["00000000-0000-0000-0000-000000000001"], "count": "more"}

    action = action_of({"kind": "quiz", "options": options})

    assert action is not None
    assert "source_ids" not in action["options"]  # type: ignore[operator]
    assert action["options"]["count"] == "more"  # type: ignore[index]


def test_the_prompt_is_one_line_of_at_most_1000_characters() -> None:
    """NB-8: the focus text is tidied like a Studio prompt."""
    long = action_of({"kind": "quiz", "prompt": "a\n  b " + "x" * 2000})
    empty = action_of({"kind": "quiz", "prompt": "   "})
    number = action_of({"kind": "quiz", "prompt": 5})

    assert long is not None and long["prompt"] == ("a b " + "x" * 2000)[:1000]
    assert empty is not None and empty["prompt"] is None
    assert number is not None and number["prompt"] is None


def test_a_word_that_only_starts_like_the_tag_is_text() -> None:
    """NB-8: `<actionable>` is not an action."""
    assert split_action("An <actionable> idea") == ("An <actionable> idea", None)


def test_the_first_tag_decides_and_every_tag_is_cut() -> None:
    """NB-8: two tags leave neither in the text."""
    raw = 'A <action>{bad</action> B <action>{"kind": "quiz"}</action> C'

    assert split_action(raw) == ("A\nB\nC", None)


# - - - through the chat - - -


async def test_the_action_is_returned_and_not_stored(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-8: `TurnView.action` has the proposal; the message has clean text."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(f"Here is a quiz.\n{QUIZ}\n{FOLLOWUPS}")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Make a quiz")

    assert turn.action is not None
    assert turn.action["kind"] == "quiz" and turn.action["prompt"] == "Calvin cycle"
    answer = turn.assistant_message.content
    assert answer.text == "Here is a quiz."
    assert answer.followups == ["Another?"]
    stored = await thread(core, student, notebook)
    assert "action" not in stored[1].content.model_dump_json()


async def test_an_invalid_action_is_dropped_but_the_answer_is_clean(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-8: no card for a proposal the Studio could not run."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text('Done.\n<action>{"kind": "poster"}</action>\n' + FOLLOWUPS)

    turn = await chat.ask_notebook.execute(student, notebook.id, "Make a poster")

    assert turn.action is None
    assert turn.assistant_message.content.text == "Done."
    assert turn.assistant_message.content.followups == ["Another?"]


async def test_the_streamed_answer_never_shows_the_tag_and_done_has_the_action(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-8: the tag is held back; `done` carries the action and the follow-ups."""
    notebook, _ = await notebook_with_source(core, student)
    raw = f"Here is a quiz.\n{QUIZ}\n{FOLLOWUPS}"
    chunks: list[str | Exception] = [raw[i : i + 5] for i in range(0, len(raw), 5)]
    scripted_llm.queue_stream(chunks)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Quiz"))

    assert names(events)[-1] == "done"
    assert streamed_text(events) == "Here is a quiz."
    assert all("<" not in e.data["text"] for e in events if e.name == "delta")
    done = events[-1].data
    assert done["action"]["kind"] == "quiz"
    assert done["message"]["text"] == "Here is a quiz."
    assert done["message"]["followups"] == ["Another?"]


async def test_an_invalid_action_in_a_stream_is_none(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-8: `done.action` is null for a bad proposal."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Ok.\n", '<action>{"kind": "x"}</action>'])

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q"))

    assert events[-1].name == "done"
    assert events[-1].data["action"] is None
    assert events[-1].data["message"]["text"] == "Ok."
