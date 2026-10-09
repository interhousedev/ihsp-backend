"""The course author assistant (lms_author): access, scope, prompt, tools, budget."""

import json
from typing import Any
from uuid import UUID

from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.errors import (
    AuthorUnavailableError,
    ChatNotFoundError,
    CourseRequiredError,
    WrongAssistantError,
)
from app.modules.ai.domain.prompts_author import AUTHOR_MARKER, CONTEXT_HEADING
from app.shared.ai_tasks import AiTask
from app.shared.base_error import RateLimitedError
from app.shared.contracts.lms import COURSE_VIEW_DRAFTS
from tests.ai.author_support import Author, arrange
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply
from tests.fakes.notebooks.assistant import FakeSource

import pytest

AUTHOR_TOOLS = [
    "get_course_outline", "get_step_draft", "list_workspace_sources",
    "search_workspace", "read_workspace_source", "list_workspace_outputs",
    "apply_outline", "create_section", "create_step", "replace_step_content",
    "add_text_block", "add_test_block", "add_flashcards_block",
    "generate_studio_output", "apply_studio_output",
]  # fmt: skip


@pytest.fixture
def a(h: AiHarness) -> Author:
    """The arranged course with the late bindings in place."""
    return arrange(h)


# - - - access and scope - - -


async def test_an_author_chat_is_bound_to_the_course_and_its_workspace(
    a: Author,
) -> None:
    """The chat stores the course and the workspace notebook (created on demand)."""
    chat = await a.chat()

    stored = a.h.store.chats[chat.id]
    assert chat.assistant == "lms_author" and chat.course_id == a.course.id
    assert stored.scope is not None and stored.scope.course_id == a.course.id
    assert stored.scope.notebook_id == a.notebooks.by_course[a.course.id]
    assert a.commands.opened == [a.course.id]
    assert stored.model == a.h.settings.ai_profile(AiTask.LMS_AUTHORING).model


async def test_the_course_is_required(a: Author) -> None:
    """Without course_id there is no author chat."""
    with pytest.raises(CourseRequiredError):
        await a.h.services.create_chat.execute(
            actor=a.teacher, assistant=Assistant.LMS_AUTHOR
        )


@pytest.mark.parametrize("who", ["student", "admin", "viewer"])
async def test_only_editors_of_the_course_may_use_it(a: Author, who: str) -> None:
    """Students, other staff and read-only staff get wrong-assistant."""
    actor = {"student": a.h.student, "admin": a.h.admin, "viewer": a.h.admin}[who]
    if who == "viewer":
        a.course.staff[actor.user_id] = (COURSE_VIEW_DRAFTS,)

    with pytest.raises(WrongAssistantError):
        await a.h.services.create_chat.execute(
            actor=actor, assistant=Assistant.LMS_AUTHOR, course_id=a.course.id
        )


async def test_losing_edit_closes_the_chat_on_the_next_call(a: Author) -> None:
    """The LMS is asked on every call: no send, no approval after removal."""
    chat = await a.chat()
    a.h.llm.push(tool_reply(("create_section", {"title": "Derivatives"})))
    card = (await a.say(chat.id)).new_messages[-1].tool_calls[0]
    a.course.staff.pop(a.teacher.user_id)

    with pytest.raises(WrongAssistantError):
        await a.say(chat.id, "again")
    with pytest.raises(WrongAssistantError):
        await a.h.services.approve_tool_call.execute(
            actor=a.teacher, chat_id=chat.id, call_id=card.id
        )
    await a.h.services.delete_chat.execute(actor=a.teacher, chat_id=chat.id)
    assert a.world.writes == []


async def test_another_person_cannot_open_the_chat(a: Author) -> None:
    """A colleague with edit on the same course still cannot read my chat."""
    chat = await a.chat()
    a.course.staff[a.h.admin.user_id] = ("edit",)

    with pytest.raises(ChatNotFoundError):
        await a.h.services.get_chat.execute(actor=a.h.admin, chat_id=chat.id)


async def test_switched_off_or_unbound_features_hide_the_assistant(
    make_harness: HarnessFactory,
) -> None:
    """LMS off, or a process without the LMS bound, answer feature-disabled."""
    off = make_harness(features={"lms": False})
    arranged = arrange(off)
    with pytest.raises(AuthorUnavailableError):
        await arranged.chat()

    bare = make_harness()
    with pytest.raises(AuthorUnavailableError):
        await bare.services.create_chat.execute(
            actor=bare.teacher,
            assistant=Assistant.LMS_AUTHOR,
            course_id=arranged.course.id,
        )


async def test_chats_are_listed_per_course(a: Author) -> None:
    """The list of author chats needs the course and shows only its chats."""
    other = a.world.add_course(a.teacher.user_id, title="Algebra")
    mine = await a.chat()
    await a.chat(other)

    page = await a.h.services.list_chats.execute(
        actor=a.teacher,
        assistant=Assistant.LMS_AUTHOR,
        cursor=None,
        limit=10,
        course_id=a.course.id,
    )

    assert [c.id for c in page.items] == [mine.id]
    with pytest.raises(CourseRequiredError):
        await a.h.services.list_chats.execute(
            actor=a.teacher, assistant=Assistant.LMS_AUTHOR, cursor=None, limit=10
        )


async def test_author_chats_are_never_shared(a: Author) -> None:
    """Unpublished drafts stay private: no share page, no transcript."""
    chat = await a.chat()
    await a.say(chat.id, "hello")
    public = a.h.services.public

    assert await public.chat_for_share(chat.id, None) is None
    assert await public.chat_transcript(a.teacher.user_id, chat.id, None) is None


# - - - prompt and context - - -


async def test_the_prompt_carries_the_course_outline_with_ids(a: Author) -> None:
    """The context lists the course, the sections and steps with their ids."""
    chat = await a.chat()
    await a.say(chat.id, "hi")

    system: str = a.h.llm.requests[-1]["system"]
    assert system.startswith("# ROLE\n" + AUTHOR_MARKER)
    context = system.split(CONTEXT_HEADING, 1)[1]
    assert "Course: Calculus" in context
    assert f"[section {a.section.id}] Limits" in context
    assert f"[step {a.step.id}] What is a limit" in context


async def test_the_context_is_refreshed_and_the_head_stays_cacheable(
    a: Author,
) -> None:
    """After a write the next request sees the new outline; the head is unchanged."""
    chat = await a.chat()
    a.h.llm.push(tool_reply(("create_section", {"title": "Derivatives"})))
    card = (await a.say(chat.id)).new_messages[-1].tool_calls[0]
    before = a.h.llm.requests[-1]["system"]

    await a.approve(chat.id, card)

    after = a.h.llm.requests[-1]["system"]
    assert "Derivatives" not in before and "] Derivatives" in after
    head = before.split(CONTEXT_HEADING)[0]
    assert after.split(CONTEXT_HEADING)[0] == head


async def test_the_author_gets_exactly_its_tools_with_closed_schemas(
    a: Author,
) -> None:
    """Fifteen tools, reads first; every nested object forbids extra keys."""
    chat = await a.chat()
    await a.say(chat.id, "hi")
    tools = a.h.llm.requests[-1]["tools"]

    assert [t["function"]["name"] for t in tools] == AUTHOR_TOOLS
    for tool in tools:
        text = json.dumps(tool["function"]["parameters"])
        assert "$ref" not in text and "$defs" not in text
        assert '"discriminator"' not in text
        _assert_closed(tool["function"]["parameters"])


def _assert_closed(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _assert_closed(item)
    elif isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False, node
        for key, value in node.items():
            if key == "properties":
                for sub in value.values():
                    _assert_closed(sub)
            else:
                _assert_closed(value)


# - - - read tools - - -


async def test_get_step_draft_numbers_the_blocks_without_ids(a: Author) -> None:
    """Blocks come numbered from 1, with the lock version and no inner ids."""
    call, sent = await a.run("get_step_draft", {"step_id": str(a.step.id)})

    data = sent["untrusted_data"]
    assert call.status == "done"
    assert (data["title"], data["lock_version"], data["blocks_total"]) == (
        "What is a limit",
        0,
        2,
    )
    assert [b["block"] for b in data["blocks"]] == [1, 2]
    assert data["blocks"][1]["cards"] == [{"front": "lim", "back": "limit"}]
    assert all("id" not in block for block in data["blocks"])


async def test_a_long_step_is_shortened_and_one_block_can_be_read_whole(
    a: Author,
) -> None:
    """Over 10 000 characters the blocks are cut; `block` reads one in full."""
    long_text = "x" * 9000
    a.step.blocks = [
        {"id": "b1", "type": "text", "markdown": long_text},
        {"id": "b2", "type": "text", "markdown": long_text},
    ]

    _, short = await a.run("get_step_draft", {"step_id": str(a.step.id)})
    _, whole = await a.run("get_step_draft", {"step_id": str(a.step.id), "block": 2})

    assert short["untrusted_data"]["note"].startswith("Some blocks are shortened")
    assert short["untrusted_data"]["blocks"][0]["shortened"] is True
    assert whole["untrusted_data"]["blocks"][0]["markdown"] == long_text


async def test_a_step_of_another_course_is_refused(a: Author) -> None:
    """Ids from the model are checked against the chat's course."""
    other = a.world.add_course(a.teacher.user_id, title="Algebra")
    foreign = a.world.add_step(other, a.world.add_section(other, "Sets"), "Union")

    call, sent = await a.run("get_step_draft", {"step_id": str(foreign.id)})

    assert call.status == "failed"
    assert sent["error"].startswith("step not found in this course")


async def test_workspace_reads_use_the_chats_notebook(a: Author) -> None:
    """search_workspace and list_workspace_sources read the course workspace."""
    a.notebooks.workspace(
        a.course, FakeSource("Textbook.pdf", "file", passages=["The epsilon limit."])
    )

    _, found = await a.run("search_workspace", {"query": "epsilon"})
    _, listed = await a.run("list_workspace_sources", {})

    hit = found["untrusted_data"]["items"][0]
    assert (hit["source_title"], hit["text"]) == ("Textbook.pdf", "The epsilon limit.")
    assert [s["title"] for s in listed["untrusted_data"]["items"]] == ["Textbook.pdf"]


# - - - write tools - - -


async def test_apply_outline_shows_the_tree_and_creates_only_new_parts(
    a: Author,
) -> None:
    """Existing titles are reused; the card marks new and existing parts."""
    limits = [{"title": "What is a limit"}, {"title": "One-sided"}]
    derivatives = [{"title": "Definition", "brief": "Goals"}]
    outline = {
        "sections": [
            {"title": "limits", "steps": limits},
            {"title": "Derivatives", "steps": derivatives},
        ],
        "add_briefs": True,
    }

    chat_id, card = await a.propose("apply_outline", outline)
    assert card.status == "pending_approval" and card.preview is not None
    assert card.preview.title.startswith("Add 1 sections and 2 steps")
    assert card.preview.items[0] == "Section “limits” (already exists)"
    assert "Step “One-sided” (new)" in card.preview.items[2]

    sent = await a.approve(chat_id, card)

    created = sent["untrusted_data"]["created_steps"]
    assert [s["title"] for s in created] == ["One-sided", "Definition"]
    new = a.world.steps[UUID(created[1]["step_id"])]
    assert new.via == "ai" and new.blocks[0]["markdown"] == "Goals"


async def test_an_outline_with_nothing_new_is_not_proposed(a: Author) -> None:
    """A repeated apply_outline fails instead of showing an empty card."""
    outline = {
        "sections": [{"title": "Limits", "steps": [{"title": "What is a limit"}]}]
    }

    call, sent = await a.run("apply_outline", outline)

    assert call.status == "failed" and "nothing to create" in sent["error"]


async def test_add_test_block_shows_the_answers_and_appends_via_ai(a: Author) -> None:
    """The card lists each question with its right answer; the block is appended."""
    questions = [
        {
            "type": "single",
            "prompt": "lim 1/x as x → ∞?",
            "options": [{"text": "0", "correct": True}, {"text": "∞"}],
        },
        {"type": "number", "prompt": "lim (2x) at x = 3?", "number": 6},
    ]
    chat_id, card = await a.propose(
        "add_test_block", {"step_id": str(a.step.id), "questions": questions}
    )
    assert card.preview is not None
    assert card.preview.items == [
        "1. lim 1/x as x → ∞? → 0",
        "2. lim (2x) at x = 3? → 6.0",
    ]

    sent = await a.approve(chat_id, card)

    assert sent["untrusted_data"]["block"] == 3
    assert [b["type"] for b in a.step.blocks] == ["text", "flashcards", "test"]
    assert (a.step.via, a.step.lock_version) == ("ai", 1)


async def test_a_broken_question_is_returned_to_the_model(a: Author) -> None:
    """Two correct options in a single choice question: no card, a fixable error."""
    questions = [
        {
            "type": "single",
            "prompt": "Pick one",
            "options": [{"text": "a", "correct": True}, {"text": "b", "correct": True}],
        }
    ]

    call, sent = await a.run(
        "add_test_block", {"step_id": str(a.step.id), "questions": questions}
    )

    assert call.status == "failed"
    assert "exactly one correct option" in sent["error"]


async def test_replace_step_keeps_blocks_by_number_and_lists_removed_ones(
    a: Author,
) -> None:
    """A kept block keeps its id; the card shows new, kept and removed blocks."""
    kept_id = a.step.blocks[1]["id"]
    args = {
        "step_id": str(a.step.id),
        "lock_version": 0,
        "title": "Limits: the idea",
        "blocks": [
            {"type": "text", "markdown": "### Idea\nApproaching a value."},
            {"type": "keep", "block": 2},
        ],
    }

    chat_id, card = await a.propose("replace_step_content", args)
    assert card.preview is not None
    assert card.preview.items == [
        "Text: ### Idea",
        "Block 2 kept: Flash cards: 1",
        "Block 1 removed: Text: A limit is the value a function approaches.",
    ]
    assert card.preview.fields[0].value == "Limits: the idea"

    await a.approve(chat_id, card)

    assert a.step.title == "Limits: the idea"
    assert a.step.blocks[1]["id"] == kept_id and a.step.via == "ai"


async def test_a_stale_lock_version_asks_the_model_to_reread(a: Author) -> None:
    """The conflict message tells the model what to do (once)."""
    args = {
        "step_id": str(a.step.id),
        "lock_version": 7,
        "title": "T",
        "blocks": [{"type": "text", "markdown": "x"}],
    }

    call, sent = await a.run("replace_step_content", args)

    assert call.status == "failed"
    assert sent["error"].startswith("draft-conflict")
    assert "current lock_version 0" in sent["error"]


async def test_an_append_keeps_what_the_teacher_saved_meanwhile(a: Author) -> None:
    """An approved append reads the fresh draft: the editor's change survives."""
    chat_id, card = await a.propose(
        "add_text_block", {"step_id": str(a.step.id), "markdown": "More."}
    )
    a.step.blocks.append({"id": "b-mine", "type": "text", "markdown": "Mine."})
    a.step.lock_version = 5  # the teacher saved in the editor meanwhile

    sent = await a.approve(chat_id, card)

    assert sent["untrusted_data"]["block"] == 4
    assert [b.get("markdown") for b in a.step.blocks[2:]] == ["Mine.", "More."]


async def test_create_step_refuses_a_duplicate_and_adds_a_new_one(a: Author) -> None:
    """A step title that exists in the section is not proposed again."""
    dup, dup_sent = await a.run(
        "create_step", {"section_id": a.section.id, "title": "what is a LIMIT"}
    )
    chat_id, card = await a.propose(
        "create_step", {"section_id": a.section.id, "title": "One-sided limits"}
    )
    sent = await a.approve(chat_id, card)

    assert dup.status == "failed" and "already exists" in dup_sent["error"]
    assert sent["untrusted_data"]["title"] == "One-sided limits"
    assert len(a.section.steps) == 2


async def test_studio_outputs_are_started_and_applied_in_the_workspace(
    a: Author,
) -> None:
    """generate_studio_output queues in the workspace; apply targets the step."""
    chat_id, card = await a.propose(
        "generate_studio_output", {"kind": "quiz", "difficulty": "hard"}
    )
    await a.approve(chat_id, card)
    quiz = a.notebooks.ready_output(
        a.course, "quiz", "Limits quiz", {"questions": [{}]}
    )
    apply_id, apply_card = await a.propose(
        "apply_studio_output",
        {"artifact_id": str(quiz), "target_step_id": str(a.step.id)},
    )
    await a.approve(apply_id, apply_card)

    requested = a.commands.requested[0]
    workspace = a.notebooks.by_course[a.course.id]
    assert (requested["notebook_id"], requested["kind"]) == (workspace, "quiz")
    assert requested["options"] == {"difficulty": "hard"}
    assert apply_card.preview is not None
    assert apply_card.preview.items == ["Test: 1 questions"]
    assert a.commands.applied[0]["target_step_id"] == a.step.id


async def test_options_of_another_kind_are_refused(a: Author) -> None:
    """depth belongs to a course plan, not to a quiz."""
    call, sent = await a.run(
        "generate_studio_output", {"kind": "quiz", "depth": "detailed"}
    )

    assert call.status == "failed" and "depth: not an option of quiz" in sent["error"]


# - - - budget and limits - - -


async def test_author_tokens_count_in_the_course_staff_pool(a: Author) -> None:
    """The author's tokens go to the ai:lms pool, not to the assistants' pool."""
    chat = await a.chat()
    a.h.llm.push(text_reply("Hello", tokens=1000))
    await a.say(chat.id, "hi")

    usage = await a.h.services.get_usage.execute(
        actor=a.teacher, assistant=Assistant.LMS_AUTHOR, course_id=a.course.id
    )

    assert a.h.budget.days == {} and a.h.course_budget.days
    limits = a.h.settings.limits
    assert usage.day.used > 0 and usage.day.limit == limits.lms_ai_daily_tokens
    assert usage.session.limit == limits.lms_ai_session_tokens


async def test_a_turn_stops_after_the_author_tool_rounds(
    make_harness: HarnessFactory,
) -> None:
    """lms_ai_max_tool_steps bounds the rounds of one author turn."""
    h = make_harness(limits={"lms_ai_max_tool_steps": 2, "ai_max_tool_steps": 8})
    a = arrange(h)
    chat = await a.chat()
    h.llm.push(*[tool_reply(("get_course_outline", {})) for _ in range(5)])

    result = await a.say(chat.id)

    assert result.status is TurnStatus.DONE
    assert len(h.llm.requests) == 2


async def test_messages_per_minute_are_limited(make_harness: HarnessFactory) -> None:
    """The per-minute limit of course staff applies to author turns."""
    h = make_harness(limits={"lms_ai_chat_per_minute": 1})
    a = arrange(h)
    chat = await a.chat()
    await a.say(chat.id, "one")

    with pytest.raises(RateLimitedError):
        await a.say(chat.id, "two")
