"""Faithfulness check of a Studio output: a small model compares it with its sources."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Final

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.artifacts.handler import ProcessedOutput
from app.modules.notebooks.domain.retrieval_plan import (
    FAITHFULNESS_SCHEMA,
    FAITHFULNESS_SCHEMA_NAME,
    FAITHFULNESS_SYSTEM,
    clean_queries,
    faithfulness_message,
)
from app.modules.notebooks.domain.tokens import Usage
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)

VERIFICATION_KEY: Final = "verification"  # in `artifacts.content`
UNVERIFIED: Final = "unverified"
CHECK_MAX_TOKENS: Final = 400
MATERIAL_MAX_CHARS: Final = 40_000  # about 10k tokens of the output
SOURCES_MAX_CHARS: Final = 240_000  # about 60k tokens: the cheap model reads it all
UNSUPPORTED_MAX: Final = 10

# Makes the output again; None when that attempt failed.
Regenerate = Callable[[], Awaitable[ProcessedOutput | None]]


@dataclass(frozen=True, slots=True)
class Verdict:
    """`faithful` is None when the check could not run."""

    faithful: bool | None
    unsupported: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class Checked:
    """The output to store and the usage of the checks."""

    output: ProcessedOutput
    usage: Usage


def _marked(output: ProcessedOutput, unsupported: list[str]) -> ProcessedOutput:
    """The output with `verification: {status: unverified, unsupported}`."""
    mark = {"status": UNVERIFIED, "unsupported": unsupported}
    return replace(output, content={**output.content, VERIFICATION_KEY: mark})


class FaithfulnessCheck:
    """Checks claims against sources; one regeneration, then "unverified".

    Best effort: a failing check delivers the output unchanged, and nothing is
    ever retried more than once. Switched by `NOTEBOOKS__FAITHFULNESS_CHECK`.
    """

    def __init__(self, llm: NotebookLlm, settings: Settings) -> None:
        """Store the model and the settings."""
        self.llm = llm
        self.settings = settings

    async def ensure(
        self, output: ProcessedOutput, sources: str, regenerate: Regenerate
    ) -> Checked:
        """The output to store: as is, regenerated, or marked unverified."""
        if not self.settings.notebooks.faithfulness_check or not sources:
            return Checked(output, Usage())
        first = await self.verify(output, sources)
        if first.faithful is not False:
            return Checked(output, first.usage)
        again = await regenerate()
        if again is None:
            return Checked(_marked(output, first.unsupported), first.usage)
        second = await self.verify(again, sources)
        usage = first.usage + second.usage
        if second.faithful is False:
            return Checked(_marked(again, second.unsupported), usage)
        return Checked(again, usage)

    async def verify(self, output: ProcessedOutput, sources: str) -> Verdict:
        """One small-model verdict on the output's claims."""
        material = json.dumps(output.content, ensure_ascii=False)[:MATERIAL_MAX_CHARS]
        message = faithfulness_message(material, sources[:SOURCES_MAX_CHARS])
        try:
            done = await self.llm.json(
                task=AiTask.STUDIO_FAITHFULNESS,
                system=FAITHFULNESS_SYSTEM,
                messages=[{"role": "user", "content": message}],
                schema_name=FAITHFULNESS_SCHEMA_NAME,
                schema=FAITHFULNESS_SCHEMA,
                max_tokens=self.llm.max_tokens(
                    AiTask.STUDIO_FAITHFULNESS, CHECK_MAX_TOKENS
                ),
            )
        except (AiProviderError, AiInvalidOutputError) as exc:
            log.info("notebooks.faithfulness.skipped", error=type(exc).__name__)
            return Verdict(None)
        faithful = done.data.get("faithful")
        unsupported = clean_queries(done.data.get("unsupported"), UNSUPPORTED_MAX)
        return Verdict(
            faithful if isinstance(faithful, bool) else None, unsupported, done.usage
        )
