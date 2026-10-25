"""What translating a subject name needs: the model and the names store."""

from collections.abc import Mapping, Sequence
from typing import Protocol
from uuid import UUID


class SubjectTranslator(Protocol):
    """Translates the missing language names of a subject."""

    async def translate(
        self, known: Mapping[str, str], missing: Sequence[str]
    ) -> dict[str, str]:
        """Return a name for each language in ``missing`` it could translate.

        Raises:
            AiProviderError: The model could not be reached.
            AiInvalidOutputError: The answer was not usable.
        """
        ...


class SubjectNamesStore(Protocol):
    """The name map of a subject."""

    async def names(self, subject_id: UUID) -> dict[str, str] | None:
        """Return the names or None when the subject does not exist."""
        ...

    async def fill_missing(
        self, subject_id: UUID, names: Mapping[str, str]
    ) -> dict[str, str]:
        """Write the names of the languages still empty; return those written."""
        ...
