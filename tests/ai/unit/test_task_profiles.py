"""AI-13: each assistant call runs with the profile of its AI task."""

from app.modules.ai.application.continue_turn import MAX_OUTPUT_TOKENS
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import (
    ChatMessage,
    ChatTier,
    MessageContent,
    MessageRole,
)
from app.settings_ai import AiTaskSettings
from app.shared.ai_tasks import AiTask
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness, HarnessFactory


async def test_a_default_request_carries_the_default_profile(h: AiHarness) -> None:
    """No overrides: the default model, 0.2, reasoning off, no provider object."""
    chat = await h.new_chat()

    await h.say(chat.id, "hello")

    request = h.llm.requests[-1]
    assert request["model"] == h.settings.ai.default.model
    assert request["max_tokens"] == MAX_OUTPUT_TOKENS
    assert request["provider"] is None
    tuning = request["tuning"]
    assert (tuning.temperature, tuning.reasoning_effort, tuning.fallbacks) == (
        0.2,
        "none",
        (),
    )


async def test_the_student_task_override_reaches_the_model_call(
    make_harness: HarnessFactory,
) -> None:
    """Model, size, temperature, reasoning, fallbacks and provider order."""
    h = make_harness(
        tasks={
            AiTask.STUDENT_CHAT: AiTaskSettings(
                model="x/student",
                max_output_tokens=777,
                temperature=0.6,
                reasoning_effort="low",
                fallbacks=("x/backup",),
                data_collection="deny",
                provider_order=("anthropic",),
            )
        }
    )
    chat = await h.new_chat()

    await h.say(chat.id, "hello")

    request = h.llm.requests[-1]
    assert request["model"] == "x/student"
    assert h.store.chats[chat.id].model == "x/student"
    assert request["max_tokens"] == 777
    assert request["provider"] == {"data_collection": "deny", "order": ["anthropic"]}
    tuning = request["tuning"]
    assert (tuning.temperature, tuning.reasoning_effort, tuning.fallbacks) == (
        0.6,
        "low",
        ("x/backup",),
    )


async def test_the_tiers_and_the_admin_assistant_are_separate_tasks(
    make_harness: HarnessFactory,
) -> None:
    """Changing one task leaves the others on the default."""
    h = make_harness(
        tasks={
            AiTask.STUDENT_CHAT_SMART: AiTaskSettings(model="x/smart"),
            AiTask.ADMIN_CHAT: AiTaskSettings(model="x/admin", temperature=0.0),
        }
    )
    fast = await h.new_chat()
    smart = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, tier=ChatTier.SMART
    )
    admin = await h.new_chat(assistant=Assistant.ADMIN)

    await h.say(fast.id, "one")
    await h.say(smart.id, "two")
    await h.say(admin.id, "three", actor=h.admin)

    models = [request["model"] for request in h.llm.requests]
    assert models == [h.settings.ai.default.model, "x/smart", "x/admin"]
    assert h.llm.requests[-1]["tuning"].temperature == 0.0


async def test_the_chat_summary_is_its_own_task(make_harness: HarnessFactory) -> None:
    """CHAT_SUMMARY picks the summarizer's model, size and tuning."""
    h = make_harness(
        tasks={
            AiTask.CHAT_SUMMARY: AiTaskSettings(
                model="x/summary", max_output_tokens=222, temperature=0.0
            )
        }
    )
    chat = await h.new_chat()
    h.store.messages[chat.id] = [
        ChatMessage(
            id=new_id(),
            chat_id=chat.id,
            seq=seq,
            role=MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
            content=MessageContent(text=f"message {seq}"),
            created_at=h.clock.now(),
        )
        for seq in range(1, 32)
    ]

    await h.say(chat.id, "and now?")

    summary, answer = h.llm.requests
    assert (summary["model"], summary["max_tokens"]) == ("x/summary", 222)
    tuning = summary["tuning"]
    assert (tuning.temperature, tuning.reasoning_effort) == (0.0, "none")
    assert answer["model"] == h.settings.ai.default.model
    assert answer["max_tokens"] == MAX_OUTPUT_TOKENS
