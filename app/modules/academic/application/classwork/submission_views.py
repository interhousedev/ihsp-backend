"""Builds the JSON of homework submissions for the student and the teacher."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.domain.classwork.records import SubmissionRecord
from app.modules.academic.domain.classwork.submission_rules import submission_status
from app.shared.contracts.files import FileRef, FilesApi

DOWNLOAD_TTL_SECONDS = 3600


class SubmissionViewBuilder:
    """Resolves the stored files behind a submission."""

    def __init__(self, files: FilesApi) -> None:
        """Store the files port."""
        self.files = files

    async def _refs(self, file_ids: Sequence[Any]) -> dict[Any, FileRef]:
        return await self.files.get_many(list(file_ids))

    async def student_view(self, record: SubmissionRecord, due: Any) -> dict[str, Any]:
        """``HomeworkSubmission``: the student's own submission, files by id."""
        refs = await self._refs(record.file_ids)
        return {
            "lesson_id": str(record.lesson_id),
            "status": submission_status(record.submitted_at, due),
            "files": [_file(refs[i]) for i in record.file_ids if i in refs],
            "comment": record.comment,
            "submitted_at": record.submitted_at.isoformat(),
        }

    async def teacher_files(
        self, records: Sequence[SubmissionRecord]
    ) -> dict[Any, Any]:
        """Files of every record with a download link, by file id.

        The link is the narrow grant: the caller has already checked that the user
        teaches the lesson, so no per-file access check runs here.
        """
        ids = list(dict.fromkeys(i for r in records for i in r.file_ids))
        refs = await self._refs(ids)
        out: dict[Any, Any] = {}
        for file_id, ref in refs.items():
            url = await self.files.download_url(
                file_id, ttl_seconds=DOWNLOAD_TTL_SECONDS
            )
            out[file_id] = {**_file(ref), "download_url": url}
        return out


def _file(ref: FileRef) -> dict[str, Any]:
    return {
        "id": str(ref.id),
        "name": ref.name,
        "size": ref.byte_size,
        "content_type": ref.content_type,
    }
