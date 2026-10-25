"""Task ``academic.translate_subject``: translate the missing names of an EMIS subject.

Kicked after the EMIS subject sync commits, with the ``subject_id`` (string).
"""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.modules.academic.application.schedule.translate_subject import (
    TranslateSubject,
)
from app.modules.academic.infrastructure.schedule.subject_translation import (
    LlmSubjectTranslator,
    SqlSubjectNamesStore,
)


@broker.task(task_name="academic.translate_subject")
async def translate_subject(subject_id: str) -> list[str]:
    """Fill the empty languages of the subject name; return the languages written."""
    container = get_container()
    case = TranslateSubject(
        SqlSubjectNamesStore(container.sessionmaker),
        LlmSubjectTranslator(container.llm, container.settings),
    )
    return sorted(await case.execute(UUID(subject_id)))
