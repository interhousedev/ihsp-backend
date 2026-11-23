"""The LMS lesson AI model calls through the platform's LLM gateway.

The recording gateway applies prompt overrides (slots of `prompt_slots`), records
the usage ledger and refuses revoked users; the task picks the model profile.
"""

from typing import Any

from app.modules.lms.ports.lesson_ai import LessonTask
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway


class LessonModelAdapter:
    """Implements ``LessonModel`` with `LlmGateway.complete_json`."""

    def __init__(self, llm: LlmGateway, settings: Settings) -> None:
        """Store the gateway and the settings (model profiles)."""
        self.llm = llm
        self.settings = settings

    async def complete_json(
        self,
        *,
        task: LessonTask,
        system: str,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Run the task's model and return the parsed document."""
        profile = self.settings.ai_profile(AiTask(task))
        result = await self.llm.complete_json(
            model=profile.model,
            system=system,
            messages=list(messages),
            schema_name=schema_name,
            schema=schema,
            max_tokens=profile.output_tokens(max_tokens),
            provider=profile.provider(require_parameters=True),
            tuning=profile.tuning,
        )
        data: dict[str, Any] = result["data"]
        return data
