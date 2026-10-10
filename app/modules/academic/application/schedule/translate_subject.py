"""Task ``academic.translate_subject``: fill the missing languages of a subject name."""

from uuid import UUID

from app.modules.academic.application.schedule.ports.subject_translation import (
    SubjectNamesStore,
    SubjectTranslator,
)
from app.modules.academic.domain.schedule.subject_names import (
    known_names,
    missing_locales,
    parse_translation,
)
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)


class TranslateSubject:
    """One model call per subject; a filled language is never touched again."""

    def __init__(self, store: SubjectNamesStore, translator: SubjectTranslator) -> None:
        """Store the collaborators."""
        self.store = store
        self.translator = translator

    async def execute(self, subject_id: UUID) -> dict[str, str]:
        """Translate what is missing and return the names written.

        Nothing to translate means no call. A failed or unusable answer leaves the
        names as they are (the next EMIS sync tries again).
        """
        names = await self.store.names(subject_id)
        if names is None:
            return {}
        missing = missing_locales(names)
        if not missing:
            return {}
        try:
            data = await self.translator.translate(known_names(names), missing)
        except (AiProviderError, AiInvalidOutputError) as error:
            log.warning(
                "subject_translate_failed",
                subject_id=str(subject_id),
                error=type(error).__name__,
            )
            return {}
        found = parse_translation(data, missing)
        if not found:
            return {}
        return await self.store.fill_missing(subject_id, found)
