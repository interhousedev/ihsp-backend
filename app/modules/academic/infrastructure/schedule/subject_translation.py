"""Subject name translation over the language model and PostgreSQL."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.schedule.subject import LANGUAGES
from app.modules.academic.domain.schedule.subject_names import (
    SCHEMA,
    SCHEMA_NAME,
    SYSTEM_PROMPT,
    request_message,
)
from app.modules.academic.infrastructure.orm import Subject
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import LlmGateway

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MAX_TOKENS = 200


class LlmSubjectTranslator:
    """Asks the cheap `subject_translate` model for the missing names."""

    def __init__(self, llm: LlmGateway, settings: Settings) -> None:
        """Store the gateway and the settings."""
        self.llm = llm
        self.settings = settings

    async def translate(
        self, known: Mapping[str, str], missing: Sequence[str]
    ) -> dict[str, str]:
        """Return the translated names of the ``missing`` languages."""
        profile = self.settings.ai_profile(AiTask.SUBJECT_TRANSLATE)
        names = {code: known.get(code, "") for code in LANGUAGES}
        result = await self.llm.complete_json(
            model=profile.model,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": request_message(names)}],
            schema_name=SCHEMA_NAME,
            schema=SCHEMA,
            max_tokens=profile.output_tokens(MAX_TOKENS),
            provider=profile.provider(require_parameters=True),
            tuning=profile.tuning,
        )
        data: dict[str, Any] = result["data"]
        return {code: str(data.get(code) or "") for code in missing}


class SqlSubjectNamesStore:
    """Reads and fills the name map in its own short transaction."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    async def names(self, subject_id: UUID) -> dict[str, str] | None:
        """Return the names or None."""
        async with self.sessionmaker() as session:
            row = await session.get(Subject, subject_id)
            return None if row is None else dict(row.name)

    async def fill_missing(
        self, subject_id: UUID, names: Mapping[str, str]
    ) -> dict[str, str]:
        """Write the names of the languages that are empty now (row locked)."""
        async with self.sessionmaker() as session, session.begin():
            row = (
                await session.execute(
                    sa.select(Subject).where(Subject.id == subject_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                return {}
            current = dict(row.name)
            written = {
                code: value
                for code, value in names.items()
                if code in LANGUAGES and not (current.get(code) or "").strip()
            }
            if written:
                row.name = {**current, **written}
            return written
