"""Port: the temporary marks the EMIS sync reconciles (TMP-2)."""

import datetime as dt
from collections.abc import Collection
from typing import Protocol
from uuid import UUID


class TemporaryMarkReconciler(Protocol):
    """Removes temporary marks that EMIS now has."""

    async def delete_in_emis(
        self, student_id: UUID, subject_id: UUID, dates: Collection[dt.date]
    ) -> int:
        """Delete the student's temporary marks of the subject on these dates."""
        ...
