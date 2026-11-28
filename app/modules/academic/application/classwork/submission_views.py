"""Builds the JSON of homework submissions for the student and the teacher."""

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.modules.academic.domain.classwork.records import SubmissionRecord
from app.modules.academic.domain.classwork.submission_rules import submission_status
from app.shared.contracts.files import FileRef, FilesApi

DOWNLOAD_TTL_SECONDS = 3600


class SubmissionViewBuilder:
    """Resolves the stored files behind a submission."""

    def __init__(self, files: FilesApi, people: PeopleDirectory) -> None:
        """Store the files port and the people directory (reviewer names)."""
        self.files = files
        self.people = people

    async def _refs(self, file_ids: Sequence[Any]) -> dict[Any, FileRef]:
        return await self.files.get_many(list(file_ids))

    async def student_view(self, record: SubmissionRecord, due: Any) -> dict[str, Any]:
        """``HomeworkSubmission``: the student's own submission, files by id."""
        refs = await self._refs(record.file_ids)
        reviewer = await self.people.person(record.reviewed_by)
        return {
            "lesson_id": str(record.lesson_id),
            "status": submission_status(record.submitted_at, due),
            "files": [_file(refs[i]) for i in record.file_ids if i in refs],
            "comment": record.comment,
            "submitted_at": record.submitted_at.isoformat(),
            "text": record.text,
            **review_fields(record, reviewer),
        }

    def teacher_row(
        self,
        *,
        student: Person,
        group_name: str,
        subgroup: int | None,
        record: SubmissionRecord | None,
        due: dt.date | None,
        files: Mapping[UUID, dict[str, Any]],
        reviewers: Mapping[UUID, Person],
    ) -> dict[str, Any]:
        """One row of ``HomeworkSubmissions.students`` (``record`` None: missing)."""
        status = submission_status(record.submitted_at if record else None, due)
        by = record.reviewed_by if record else None
        reviewer = reviewers.get(by) if by else None
        return {
            "id": str(record.id) if record and record.id else None,
            "student": student.to_json(),
            "group_name": group_name,
            "subgroup": subgroup,
            "status": status,
            "files": (
                [files[i] for i in record.file_ids if i in files] if record else []
            ),
            "comment": record.comment if record else None,
            "submitted_at": record.submitted_at.isoformat() if record else None,
            "text": record.text if record else None,
            **review_fields(record, reviewer),
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


def review_fields(
    record: SubmissionRecord | None, reviewer: Person | None
) -> dict[str, Any]:
    """The review part of a submission JSON (``pending`` when nothing is handed in)."""
    if record is None:
        return {
            "review_status": "pending",
            "grade": None,
            "teacher_comment": None,
            "previous_comment": None,
            "reviewed_at": None,
            "reviewer": None,
        }
    return {
        "review_status": record.review_status,
        "grade": record.grade,
        "teacher_comment": record.teacher_comment,
        "previous_comment": record.previous_comment,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "reviewer": None if reviewer is None else reviewer.to_json(),
    }
