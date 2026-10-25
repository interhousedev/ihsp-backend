"""NB-5, NB-6, NB-7, NB-14: asking the notebook, as one answer (§ 3.3.1)."""

from app.modules.notebooks.domain.entities import (
    AnchorPassages,
    AnchorText,
    ChatConfig,
)
from app.modules.notebooks.domain.enums import (
    ChatLanguage,
    ChatLength,
    ChatStyle,
    MessageRole,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import (
    BusyError,
    InvalidOptionsError,
    LimitReachedError,
    NoSourcesSelectedError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.tokens import Usage
from app.modules.notebooks.wiring_chat import ChatServices, build_chat
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.base_error import RateLimitedError
from app.shared.clock import local_today
from app.shared.contracts.ai import AiProviderError
from tests.factories.notebooks import NOW, make_message, make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    ANSWER,
    ANSWER_TEXT,
    BIG_NOTEBOOK,
    CoreFactory,
    last_message,
    notebook_with_source,
    passages_of,
    sources_block,
    thread,
)

import pytest

SMALL_CONTEXT = {"chat_full_context_tokens": 10}  # forces retrieval mode


# - - - the stored answer - - -


async def test_answer_is_stored_with_citations_and_followups(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: markers, citation snapshots and follow-ups are stored with the answer."""
    notebook, source = await notebook_with_source(core, student)
    first = (await passages_of(core, source))[0]
    scripted_llm.queue_text(ANSWER)

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "  What is photosynthesis?  "
    )

    assert (turn.user_message.seq, turn.assistant_message.seq) == (1, 2)
    assert turn.user_message.role is MessageRole.USER
    assert turn.user_message.content.text == "What is photosynthesis?"
    assert turn.user_message.content.source_ids == [source.id]
    answer = turn.assistant_message.content
    assert answer.text == ANSWER_TEXT
    cited = [(c.n, c.passage_id, c.source_id) for c in answer.citations]
    assert cited == [(1, first.id, source.id)]
    assert answer.citations[0].source_title == "Biology"
    assert answer.citations[0].source_kind is SourceKind.TEXT
    assert answer.followups == ["Where?", "Why?"]
    assert answer.grounded is True
    assert answer.retrieval is False
    assert answer.source_ids == [source.id]
    assert turn.action is None


async def test_both_messages_are_in_the_thread_after_the_call(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: user message then assistant message, readable from the database."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER)

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    stored = await thread(core, student, notebook)
    assert [m.id for m in stored] == [turn.user_message.id, turn.assistant_message.id]
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].content == turn.assistant_message.content
    assert stored[0].stopped is False and stored[1].stopped is False


async def test_an_answer_without_citations_is_not_grounded(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: no valid marker means `grounded=False` and no citations."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text("The sources do not say.\n<followups>[]</followups>")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    answer = turn.assistant_message.content
    assert answer.text == "The sources do not say."
    assert answer.citations == []
    assert answer.followups == []
    assert answer.grounded is False


async def test_sequence_numbers_continue_over_turns(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: seq 1, 2 for the first turn, 3, 4 for the next."""
    notebook, _ = await notebook_with_source(core, student)

    first = await chat.ask_notebook.execute(student, notebook.id, "One?")
    second = await chat.ask_notebook.execute(student, notebook.id, "Two?")

    seqs = [
        m.seq
        for m in (
            first.user_message,
            first.assistant_message,
            second.user_message,
            second.assistant_message,
        )
    ]
    assert seqs == [1, 2, 3, 4]


async def test_tokens_model_and_weighted_cost_are_stored(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-14: the provider's usage is kept on the answer and charged to the budget."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER, usage={"input": 1000, "output": 100, "cached": 400})
    expected = Usage(input=1000, output=100, cached=400).weighted

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    answer = turn.assistant_message
    assert (answer.tokens_in, answer.tokens_out, answer.tokens_cached) == (
        1000,
        100,
        400,
    )
    assert answer.weighted == expected
    assert answer.model == core.deps.settings.ai_profile(AiTask.NOTEBOOK_CHAT).model
    assert turn.user_message.weighted is None
    assert turn.usage.day.used == expected
    assert turn.usage.session.used == expected


async def test_a_provider_error_stores_nothing_and_charges_nothing(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `AiProviderError` propagates; thread and budget stay as they were."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_error(AiProviderError())

    with pytest.raises(AiProviderError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert await thread(core, student, notebook) == []
    assert (await core.budget.usage(student.user_id)).day.used == 0


# - - - access and validation - - -


async def test_another_students_notebook_is_not_found(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    other_student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-15: a notebook of someone else answers 404 and the model is not called."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(NotebookNotFoundError):
        await chat.ask_notebook.execute(other_student, notebook.id, "Q?")

    assert scripted_llm.calls == 0
    assert await thread(core, student, notebook) == []


async def test_a_deleted_notebook_is_not_found(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-15: a notebook in the 7-day bin cannot be asked."""
    notebook = await make_notebook(core.uow_factory, student.user_id, deleted_at=NOW)
    await make_source(core.uow_factory, notebook)

    with pytest.raises(NotebookNotFoundError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?")


@pytest.mark.parametrize("text", ["", "   \n\t ", "x" * 4001])
async def test_an_empty_or_too_long_question_is_refused(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    scripted_llm: ScriptedLlm,
    text: str,
) -> None:
    """NB-6: the trimmed question has 1 to 4 000 characters."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(InvalidOptionsError):
        await chat.ask_notebook.execute(student, notebook.id, text)

    assert scripted_llm.calls == 0


async def test_a_question_of_4000_characters_is_accepted(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: the upper limit is inclusive, after trimming."""
    notebook, _ = await notebook_with_source(core, student)

    turn = await chat.ask_notebook.execute(student, notebook.id, f" {'x' * 4000} ")

    assert turn.user_message.content.text == "x" * 4000


@pytest.mark.parametrize("case", ["pending", "foreign"])
async def test_picked_sources_that_are_not_usable_are_refused_before_the_model(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    scripted_llm: ScriptedLlm,
    case: str,
) -> None:
    """NB-5, NB-6: 422 `no-sources-selected`; nothing is called or stored."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    source_ids = None
    if case == "pending":
        await make_source(
            core.uow_factory, notebook, texts=(), status=SourceStatus.PENDING
        )
    if case == "foreign":
        elsewhere, foreign = await notebook_with_source(core, student)
        source_ids = [foreign.id]
        assert elsewhere.id != notebook.id

    with pytest.raises(NoSourcesSelectedError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?", source_ids)

    assert scripted_llm.calls == 0
    assert await thread(core, student, notebook) == []


# - - - which sources are asked - - -


async def test_only_selected_ready_and_stale_sources_are_used(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-5: unselected, pending and failed sources stay out of the context."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    ready = await make_source(core.uow_factory, notebook, title="Ready")
    await make_source(core.uow_factory, notebook, title="Unselected", selected=False)
    await make_source(
        core.uow_factory,
        notebook,
        title="Pending",
        texts=(),
        status=SourceStatus.PENDING,
    )
    await make_source(
        core.uow_factory, notebook, title="Failed", texts=(), status=SourceStatus.FAILED
    )
    stale = await make_source(
        core.uow_factory, notebook, title="Stale", status=SourceStatus.STALE
    )

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    block = sources_block(scripted_llm.text_requests[-1])
    assert 'title="Ready"' in block and 'title="Stale"' in block
    for title in ("Unselected", "Pending", "Failed"):
        assert f'title="{title}"' not in block
    assert turn.assistant_message.content.source_ids == [ready.id, stale.id]
    assert turn.user_message.content.source_ids == [ready.id, stale.id]


async def test_sources_are_labelled_by_position_not_by_request_order(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: S1 is the first source by position; the stored list follows the labels."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    later = await make_source(core.uow_factory, notebook, title="Later", position=2)
    earlier = await make_source(core.uow_factory, notebook, title="Earlier", position=1)

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "Q?", [later.id, earlier.id]
    )

    block = sources_block(scripted_llm.text_requests[-1])
    assert block.index('title="Earlier"') < block.index('title="Later"')
    assert 'id="S1" title="Earlier"' in block
    assert turn.assistant_message.content.source_ids == [earlier.id, later.id]


async def test_given_source_ids_override_the_persisted_selection(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-5: `source_ids` win over the checkboxes; foreign ids are ignored."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    await make_source(core.uow_factory, notebook, title="Checked")
    chosen = await make_source(
        core.uow_factory, notebook, title="Unchecked", selected=False
    )
    _, foreign = await notebook_with_source(core, student, title="Elsewhere")

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "Q?", [chosen.id, foreign.id, chosen.id]
    )

    block = sources_block(scripted_llm.text_requests[-1])
    assert 'title="Unchecked"' in block
    assert 'title="Checked"' not in block and 'title="Elsewhere"' not in block
    assert turn.assistant_message.content.source_ids == [chosen.id]


# - - - the prompt sent to the model - - -


async def test_first_turn_sends_the_context_then_the_question(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: [context, question]; the context carries the labelled passages."""
    notebook, _ = await notebook_with_source(core, student)

    await chat.ask_notebook.execute(student, notebook.id, "What is it?")

    request = scripted_llm.text_requests[-1]
    assert [m["role"] for m in request["messages"]] == ["user", "user"]
    block = sources_block(request)
    assert block.startswith("<sources>") and block.endswith("</sources>")
    assert "[S1:P1] Photosynthesis turns light" in block
    assert "[S1:P2] It happens in the chloroplasts" in block
    assert last_message(request) == "What is it?"


async def test_the_context_message_is_marked_for_provider_caching(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: Anthropic models get `cache_control` on the `<sources>` message."""
    notebook, _ = await notebook_with_source(core, student)

    await chat.ask_notebook.execute(student, notebook.id, "Q?")

    part = scripted_llm.text_requests[-1]["messages"][0]["content"][0]
    assert part["cache_control"] == {"type": "ephemeral"}


async def test_history_is_sent_with_plain_numbered_citations(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: earlier turns go as role/content with `[n]`, without follow-ups."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER)
    await chat.ask_notebook.execute(student, notebook.id, "First?")

    await chat.ask_notebook.execute(student, notebook.id, "Second?")

    messages = scripted_llm.text_requests[-1]["messages"]
    assert messages[1:] == [
        {"role": "user", "content": "First?"},
        {"role": "assistant", "content": "Light becomes energy [1]."},
        {"role": "user", "content": "Second?"},
    ]


async def test_only_the_last_twenty_messages_are_sent(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: ten turns of history (`ai_chat_history_limit`), oldest dropped first."""
    notebook, _ = await notebook_with_source(core, student)
    for seq in range(1, 23):
        role = MessageRole.USER if seq % 2 else MessageRole.ASSISTANT
        await make_message(core.uow_factory, notebook, role=role, text=f"m{seq}")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Now?")

    messages = scripted_llm.text_requests[-1]["messages"]
    assert len(messages) == 1 + 20 + 1
    assert messages[1]["content"] == "m3"
    assert messages[20]["content"] == "m22"
    assert turn.user_message.seq == 23


async def test_the_chat_has_no_tools_and_denies_data_collection(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6, NB-16: no tools are offered; the provider may not keep the data."""
    notebook, _ = await notebook_with_source(core, student)

    await chat.ask_notebook.execute(student, notebook.id, "Q?")

    request = scripted_llm.text_requests[-1]
    assert request["tools"] == []
    assert request["provider"] == {"data_collection": "deny"}
    assert scripted_llm.json_requests == []


@pytest.mark.parametrize(
    ("config", "needle", "max_tokens"),
    [
        (ChatConfig(), "Be a neutral, clear research assistant.", 1000),
        (ChatConfig(style=ChatStyle.LEARNING_GUIDE), "Act as a patient tutor.", 1000),
        (
            ChatConfig(style=ChatStyle.CUSTOM, custom_prompt="Explain like a pirate"),
            "«Explain like a pirate»",
            1000,
        ),
        (ChatConfig(goal="Pass the biology exam"), "«Pass the biology exam»", 1000),
        (ChatConfig(length=ChatLength.SHORTER), "At most 80 words.", 400),
        (
            ChatConfig(length=ChatLength.LONGER),
            "A thorough answer of 250 to 450 words",
            2000,
        ),
    ],
)
async def test_chat_settings_change_the_system_prompt_and_the_token_cap(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    scripted_llm: ScriptedLlm,
    config: ChatConfig,
    needle: str,
    max_tokens: int,
) -> None:
    """NB-7: style, custom text, goal and length reach the model."""
    notebook, _ = await notebook_with_source(core, student, chat_config=config)

    await chat.ask_notebook.execute(student, notebook.id, "Q?")

    request = scripted_llm.text_requests[-1]
    assert request["system"].startswith(
        "You are the notebook assistant of the IHT student platform"
    )
    assert needle in request["system"]
    assert request["max_tokens"] == max_tokens
    today = local_today(core.deps.clock)
    assert request["system"].splitlines()[-1] == f"Today is {today} (Asia/Tashkent)."


@pytest.mark.parametrize(
    ("locale", "language", "expected"),
    [
        ("ru", ChatLanguage.AUTO, "Write in Russian."),
        ("en", ChatLanguage.AUTO, "Write in English."),
        ("uz", ChatLanguage.AUTO, "Write in Uzbek (Latin script)."),
        ("ru", ChatLanguage.UZ, "Write in Uzbek (Latin script)."),
        ("uz", ChatLanguage.EN, "Write in English."),
    ],
)
async def test_language_auto_follows_the_users_locale(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
    locale: str,
    language: ChatLanguage,
    expected: str,
) -> None:
    """NB-7: `auto` is the locale of the user; a fixed language wins."""
    chat = build_chat(make_core(locale=locale))
    config = ChatConfig(language=language)
    notebook, _ = await notebook_with_source(core, student, chat_config=config)

    await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert expected in scripted_llm.text_requests[-1]["system"]


# - - - retrieval and anchors - - -


async def test_a_big_notebook_answers_from_the_best_matching_passages(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6: retrieval is flagged; hostile labels outside the pack are dropped."""
    chat = build_chat(make_core(notebooks=SMALL_CONTEXT))
    notebook, source = await notebook_with_source(core, student, texts=BIG_NOTEBOOK)
    calvin = (await passages_of(core, source))[4]
    scripted_llm.queue_text(
        "Sugar is built [[S1:P5]] and also [[S1:P1]] and [[S7:P1]].\n"
        '<followups>["Why?"]</followups>'
    )

    turn = await chat.ask_notebook.execute(student, notebook.id, "Calvin cycle?")

    block = sources_block(scripted_llm.text_requests[-1])
    assert "[S1:P5] The Calvin cycle" in block
    assert "[S1:P4]" in block and "[S1:P6]" in block  # neighbours
    assert "[S1:P1]" not in block and "[S1:P8]" not in block
    answer = turn.assistant_message.content
    assert answer.retrieval is True
    assert answer.source_ids == [source.id]
    assert [c.passage_id for c in answer.citations] == [calvin.id]
    assert answer.text == "Sugar is built ⟦1⟧ and also and."
    assert "[[" not in answer.text


async def test_a_short_follow_up_is_ranked_with_the_previous_question(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6: "and why?" matches nothing alone; the earlier question helps."""
    chat = build_chat(make_core(notebooks=SMALL_CONTEXT))
    notebook, _ = await notebook_with_source(core, student, texts=BIG_NOTEBOOK)
    await chat.ask_notebook.execute(student, notebook.id, "Calvin cycle?")

    await chat.ask_notebook.execute(student, notebook.id, "and why?")

    assert "[S1:P5]" in sources_block(scripted_llm.text_requests[-1])


async def test_anchored_passages_are_always_in_the_context(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6: a pinned passage stays in a retrieval pack and the model is told."""
    chat = build_chat(make_core(notebooks=SMALL_CONTEXT))
    notebook, source = await notebook_with_source(core, student, texts=BIG_NOTEBOOK)
    pinned = (await passages_of(core, source))[0]
    anchor = AnchorPassages(ids=[pinned.id])

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "Calvin cycle?", None, anchor
    )

    request = scripted_llm.text_requests[-1]
    assert "[S1:P1] Generic passage number 1" in sources_block(request)
    assert "[S1:P5]" in sources_block(request)
    assert last_message(request) == "Calvin cycle?\n\n[Note: Focus on passages S1:P1]"
    assert turn.user_message.content.anchor == anchor


async def test_an_anchor_text_is_named_in_the_question(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the model learns which topic the student clicked."""
    notebook, _ = await notebook_with_source(core, student)

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "Explain", None, AnchorText(text="photosynthesis")
    )

    request = scripted_llm.text_requests[-1]
    assert last_message(request) == (
        "Explain\n\n[Note: The student clicked on this topic: photosynthesis]"
    )
    assert turn.user_message.content.anchor == AnchorText(text="photosynthesis")


async def test_a_passage_of_an_unused_source_is_not_pinned(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: only passages that are in the request's context can be focused on."""
    notebook, _ = await notebook_with_source(core, student)
    off = await make_source(core.uow_factory, notebook, title="Off", selected=False)
    anchor = AnchorPassages(ids=[(await passages_of(core, off))[0].id])

    await chat.ask_notebook.execute(student, notebook.id, "Q?", None, anchor)

    request = scripted_llm.text_requests[-1]
    assert 'title="Off"' not in sources_block(request)
    assert last_message(request) == "Q?"


# - - - limits - - -


async def test_the_eleventh_question_in_a_minute_is_rate_limited(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    other_student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-14: ten questions per minute per student."""
    notebook, _ = await notebook_with_source(core, student)
    other_notebook, _ = await notebook_with_source(core, other_student)
    limit = core.deps.settings.limits.nb_chat_per_minute
    for _ in range(limit):
        await chat.ask_notebook.execute(student, notebook.id, "Q?")

    with pytest.raises(RateLimitedError):
        await chat.ask_notebook.execute(student, notebook.id, "One too many?")
    await chat.ask_notebook.execute(other_student, other_notebook.id, "Q?")

    assert scripted_llm.calls == limit + 1


async def test_an_exhausted_budget_refuses_before_any_model_call(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-14: 429 `limit-reached` with the scope; nothing is called or stored."""
    chat = build_chat(make_core(limits={"nb_daily_tokens_student": 100}))
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(LimitReachedError) as caught:
        await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert caught.value.params["scope"] == "day"
    assert "resets_at" in caught.value.params
    assert scripted_llm.calls == 0
    assert await thread(core, student, notebook) == []


async def test_a_second_question_while_one_runs_is_busy(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: one question at a time per notebook and student."""
    notebook, _ = await notebook_with_source(core, student)

    async with core.turn_lock.hold(notebook.id, student.user_id):
        with pytest.raises(BusyError):
            await chat.ask_notebook.execute(student, notebook.id, "Q?")
        assert scripted_llm.calls == 0
    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert turn.assistant_message.seq == 2


async def test_the_lock_is_released_after_a_failed_question(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: a provider error does not leave the notebook busy."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_error(AiProviderError())
    with pytest.raises(AiProviderError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert turn.assistant_message.seq == 2


@pytest.mark.parametrize("case", ["empty", "deselected"])
async def test_no_selected_source_gives_a_general_answer_that_is_flagged(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    scripted_llm: ScriptedLlm,
    case: str,
) -> None:
    """T6.3: nothing selected still answers, ungrounded, with a note to the model."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    if case == "deselected":
        await make_source(core.uow_factory, notebook, selected=False)
    scripted_llm.queue_text("A general answer.\n<followups>[]</followups>")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    answer = turn.assistant_message.content
    assert answer.text == "A general answer."
    assert answer.grounded is False and answer.citations == []
    assert answer.source_ids == []
    assert scripted_llm.calls == 1
