"""Query decomposition: a complex chat question becomes focused sub-searches."""

from collections.abc import Sequence
from typing import Final

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.application.multi_hop_retrieval import Search
from app.modules.notebooks.domain.entities import Passage
from app.modules.notebooks.domain.retrieval_plan import (
    DECOMPOSE_SCHEMA,
    DECOMPOSE_SCHEMA_NAME,
    DECOMPOSE_SYSTEM,
    clean_queries,
    decompose_message,
    interleave,
    looks_complex,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)

DECOMPOSE_MAX_TOKENS: Final = 400
MIN_HITS_PER_PART: Final = 4


class QueryDecomposer:
    """Splits a complex question (heuristic, then a small model); retrieves each.

    Only the question goes to the small model. The main model then answers from
    the interleaved best passages of every part, a shorter and more focused pack
    than one broad search, so it reads and reasons less.
    """

    def __init__(self, llm: NotebookLlm, settings: Settings) -> None:
        """Store the model and the settings."""
        self.llm = llm
        self.settings = settings

    async def parts(self, question: str) -> list[str]:
        """The sub-questions, or [] when the question is simple or the call fails."""
        notebooks = self.settings.notebooks
        if not notebooks.decompose_enabled or not looks_complex(question):
            return []
        try:
            done = await self.llm.json(
                task=AiTask.QUERY_DECOMPOSE,
                system=DECOMPOSE_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": decompose_message(
                            question, notebooks.decompose_max_parts
                        ),
                    }
                ],
                schema_name=DECOMPOSE_SCHEMA_NAME,
                schema=DECOMPOSE_SCHEMA,
                max_tokens=self.llm.max_tokens(
                    AiTask.QUERY_DECOMPOSE, DECOMPOSE_MAX_TOKENS
                ),
            )
        except (AiProviderError, AiInvalidOutputError) as exc:
            log.info("notebooks.decompose.skipped", error=type(exc).__name__)
            return []
        if done.data.get("complex") is not True:
            return []
        parts = clean_queries(done.data.get("parts"), notebooks.decompose_max_parts)
        return parts if len(parts) > 1 else []

    async def retrieve(
        self, question: str, search: Search, limit: int
    ) -> list[Passage] | None:
        """The interleaved hits of every part; None when the question is not split."""
        parts = await self.parts(question)
        if not parts:
            return None
        per_part = max(limit // len(parts), MIN_HITS_PER_PART)
        groups: Sequence[list[Passage]] = [
            await search(part, per_part) for part in parts
        ]
        return interleave(groups, limit)
