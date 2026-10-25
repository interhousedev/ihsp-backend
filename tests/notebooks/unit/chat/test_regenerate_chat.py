"""NB-6, NB-14: regenerating the last answer (§ 3.3.6)."""

from app.modules.notebooks.application.views import StreamEvent
from app.modules.notebooks.domain.entities import AnchorText
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.errors import (
    BusyError,
    InvalidOptionsError,
    LimitReachedError,
    NoSourcesSelectedError,
    NotebookNotFoundError,
)
from app.modules.notebooks.wiring_chat import ChatServices, build_chat
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import AiProviderError
from tests.factories.notebooks import make_message, make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    ANSWER,
    ANSWER_TEXT,
    CoreFactory,
    collect,
    last_message,
    names,
    notebook_with_source,
    passages_of,
    sources_block,
    streamed_text,
    thread,
)

import pytest

USER = MessageRole.USER
ASSISTANT = MessageRole.ASSISTANT
CHUNKS: list[str | Exception] = [
    "Light becomes ",
    "energy [[S1",
    ":P1]].\n",
    '<followups>["Where?"]</followups>',
]


async def test_regenerating_replaces_the_last_answer_in_its_place(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the question stays, the answer is new and keeps the old `seq`."""
    notebook, source = await notebook_with_source(core, student)
    second = (await passages_of(core, source))[1]
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    scripted_llm.queue_text("Second try [[S1:P2]].")

    turn = await chat.regenerate_chat.execute(student, notebook.id)

    assert turn.user_message.id == first.user_message.id
    assert turn.assistant_message.id != first.assistant_message.id
    assert turn.assistant_message.seq == first.assistant_message.seq == 2
    assert turn.assistant_message.content.text == "Second try ⟦1⟧."
    assert turn.assistant_message.content.citations[0].passage_id == second.id
    stored = await thread(core, student, notebook)
    assert [m.id for m in stored] == [turn.user_message.id, turn.assistant_message.id]
    request = scripted_llm.text_requests[-1]
    assert [m["role"] for m in request["messages"]] == ["user", "user"]
    assert last_message(request) == "Q?"


async def test_only_the_last_turn_changes_and_earlier_ones_are_history(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: regenerate touches the last answer only."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER)
    scripted_llm.queue_text(ANSWER)
    one = await chat.ask_notebook.execute(student, notebook.id, "One?")
    two = await chat.ask_notebook.execute(student, notebook.id, "Two?")

    turn = await chat.regenerate_chat.execute(student, notebook.id)

    stored = await thread(core, student, notebook)
    assert [m.id for m in stored[:3]] == [
        one.user_message.id,
        one.assistant_message.id,
        two.user_message.id,
    ]
    assert stored[3].id == turn.assistant_message.id and stored[3].seq == 4
    assert scripted_llm.text_requests[-1]["messages"][1:] == [
        {"role": "user", "content": "One?"},
        {"role": "assistant", "content": "Light becomes energy [1]."},
        {"role": "user", "content": "Two?"},
    ]


@pytest.mark.parametrize(
    "roles",
    [
        [],
        [USER],
        [ASSISTANT],
        [USER, ASSISTANT, USER],
        [USER, ASSISTANT, ASSISTANT],
    ],
)
async def test_only_a_question_with_its_answer_can_be_regenerated(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    scripted_llm: ScriptedLlm,
    roles: list[MessageRole],
) -> None:
    """NB-6: the thread must end with a question and an answer."""
    notebook, _ = await notebook_with_source(core, student)
    for role in roles:
        await make_message(core.uow_factory, notebook, role=role, text="Text")

    with pytest.raises(InvalidOptionsError) as caught:
        await chat.regenerate_chat.execute(student, notebook.id)

    assert caught.value.params == {"reason": "nothing-to-regenerate"}
    assert scripted_llm.calls == 0
    assert len(await thread(core, student, notebook)) == len(roles)


async def test_the_stored_sources_and_anchor_of_the_question_are_used_again(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-5, NB-6: the same sources and topic, whatever the checkboxes say now."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    await make_source(core.uow_factory, notebook, title="A")
    chosen = await make_source(core.uow_factory, notebook, title="B", selected=False)
    anchor = AnchorText(text="topic")
    await chat.ask_notebook.execute(
        student, notebook.id, "Explain", [chosen.id], anchor
    )

    turn = await chat.regenerate_chat.execute(student, notebook.id)

    request = scripted_llm.text_requests[-1]
    block = sources_block(request)
    assert 'title="B"' in block and 'title="A"' not in block
    assert last_message(request) == (
        "Explain\n\n[Note: The student clicked on this topic: topic]"
    )
    assert turn.assistant_message.content.source_ids == [chosen.id]
    assert turn.user_message.content.anchor == anchor


async def test_regenerating_without_a_usable_source_is_refused(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: 422 when the question's sources are gone; the old answer stays."""
    notebook, source = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    async with core.uow_factory() as uow:
        await uow.sources.delete(source.id)
        await uow.commit()
    calls = scripted_llm.calls

    with pytest.raises(NoSourcesSelectedError):
        await chat.regenerate_chat.execute(student, notebook.id)

    stored = await thread(core, student, notebook)
    assert [m.id for m in stored] == [first.user_message.id, first.assistant_message.id]
    assert scripted_llm.calls == calls


async def test_a_provider_error_keeps_the_old_answer(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the old answer is deleted only when the new one is stored."""
    notebook, _ = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    scripted_llm.queue_error(AiProviderError())

    with pytest.raises(AiProviderError):
        await chat.regenerate_chat.execute(student, notebook.id)

    stored = await thread(core, student, notebook)
    assert [m.id for m in stored] == [first.user_message.id, first.assistant_message.id]


async def test_another_students_notebook_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor, other_student: Actor
) -> None:
    """NB-15: regenerating in someone else's notebook answers 404."""
    notebook, _ = await notebook_with_source(core, student)
    await chat.ask_notebook.execute(student, notebook.id, "Q?")

    with pytest.raises(NotebookNotFoundError):
        await chat.regenerate_chat.execute(other_student, notebook.id)


async def test_regenerating_shares_the_rate_limit_of_questions(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-14: ten model calls per minute, questions and regenerations together."""
    notebook, _ = await notebook_with_source(core, student)
    limit = core.deps.settings.limits.nb_chat_per_minute
    for _ in range(limit - 1):
        await chat.ask_notebook.execute(student, notebook.id, "Q?")
    await chat.regenerate_chat.execute(student, notebook.id)

    with pytest.raises(RateLimitedError):
        await chat.regenerate_chat.execute(student, notebook.id)


async def test_regenerating_while_a_question_runs_is_busy(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: one model call at a time per notebook and student."""
    notebook, _ = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    async with core.turn_lock.hold(notebook.id, student.user_id):
        with pytest.raises(BusyError):
            await chat.regenerate_chat.execute(student, notebook.id)

    stored = await thread(core, student, notebook)
    assert stored[1].id == first.assistant_message.id


async def test_regenerating_is_refused_when_the_budget_is_used_up(
    core: NotebooksCore,
    chat: ChatServices,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-14: 429 before the model is called; the old answer stays."""
    notebook, _ = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    tight = build_chat(make_core(limits={"nb_daily_tokens_student": 100}))
    calls = scripted_llm.calls

    with pytest.raises(LimitReachedError):
        await tight.regenerate_chat.execute(student, notebook.id)

    assert scripted_llm.calls == calls
    stored = await thread(core, student, notebook)
    assert stored[1].id == first.assistant_message.id


# - - - streaming - - -


async def test_a_regenerated_stream_starts_with_the_existing_question(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `message` names the old user message; `done` has the new answer."""
    notebook, _ = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    scripted_llm.queue_stream(CHUNKS)

    events = await collect(chat.regenerate_chat.stream(student, notebook.id))

    assert names(events)[0] == "message" and names(events)[-1] == "done"
    assert events[0] == StreamEvent(
        "message", {"id": str(first.user_message.id), "seq": 1}
    )
    assert streamed_text(events) == ANSWER_TEXT
    message = events[-1].data["message"]
    assert message["seq"] == 2 and message["id"] != str(first.assistant_message.id)
    stored = await thread(core, student, notebook)
    assert [m.id for m in stored] == [first.user_message.id, stored[1].id]
    assert str(stored[1].id) == message["id"]


async def test_stopping_a_regeneration_replaces_the_old_answer_with_the_partial(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: what the student saw of the new answer is what stays."""
    notebook, _ = await notebook_with_source(core, student)
    first = await chat.ask_notebook.execute(student, notebook.id, "Q?")
    scripted_llm.queue_stream(["Fresh start [[S1:P1]] ", "and the rest."])
    events = chat.regenerate_chat.stream(student, notebook.id)

    async for event in events:
        if "⟦" in event.data.get("text", ""):
            break
    await events.aclose()

    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [USER, ASSISTANT]
    assert stored[0].id == first.user_message.id
    assert stored[1].id != first.assistant_message.id and stored[1].seq == 2
    assert stored[1].stopped is True
    assert stored[1].content.text == "Fresh start ⟦1⟧"
