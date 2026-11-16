"""SQL repositories of the profile slice."""

import datetime as dt
from typing import cast
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.profile import AccountKind, AdmissionProfile, Stage
from app.modules.admission.domain.profile_words import (
    ReviewRecord,
    ReviewStatus,
    SafetyFlag,
    WordsSource,
    WordsState,
)
from app.modules.admission.infrastructure.orm.profile import (
    ProfileRow,
    ProfileWordsHistoryRow,
    ProfileWordsRow,
    ReviewRow,
)
from app.shared.ids import new_id

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _profile(row: ProfileRow) -> AdmissionProfile:
    return AdmissionProfile(
        student_id=row.student_id,
        account_kind=cast(AccountKind, row.account_kind),
        stage=cast(Stage, row.stage),
        question_set_version=row.question_set_version,
        answers=dict(row.answers),
        setup_completed_at=row.setup_completed_at,
        lock_version=row.lock_version,
    )


def _words(row: ProfileWordsRow) -> WordsState:
    cands = row.candidates.get("items", []) if row.candidates else []
    return WordsState(
        student_id=row.student_id,
        words=tuple(row.words),
        candidates=list(cands),
        source=cast(WordsSource, row.source),
        version=row.version,
        confirmed_at=row.confirmed_at,
        lock_version=row.lock_version,
    )


def _review(row: ReviewRow) -> ReviewRecord:
    return ReviewRecord(
        student_id=row.student_id,
        target_kind=row.target_kind,
        target_id=row.target_id,
        input_hash=row.input_hash,
        task=row.task,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        model=row.model,
        rubric_version=row.rubric_version,
        words_version=row.words_version,
        grades=dict(row.grades),
        overall=row.overall,
        payload=dict(row.payload),
        safety_flag=cast(SafetyFlag, row.safety_flag),
        status=cast(ReviewStatus, row.status),
        id=row.id,
        created_at=row.created_at,
    )


class SqlProfileRepository:
    """Profiles and the three words."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def get(self, student_id: UUID) -> AdmissionProfile | None:
        """Return the profile, if it exists."""
        row = await self._s.get(ProfileRow, student_id)
        return _profile(row) if row else None

    async def save(
        self, profile: AdmissionProfile, expected_lock: int | None
    ) -> AdmissionProfile:
        """Insert (expected None) or update under the lock counter."""
        if expected_lock is None:
            row = ProfileRow(
                student_id=profile.student_id,
                account_kind=profile.account_kind,
                stage=profile.stage,
                question_set_version=profile.question_set_version,
                answers=profile.answers,
                setup_completed_at=profile.setup_completed_at,
                lock_version=0,
            )
            self._s.add(row)
        else:
            found = await self._s.get(
                ProfileRow, profile.student_id, with_for_update=True
            )
            if found is None or found.lock_version != expected_lock:
                raise AdmissionConflictError()
            row = found
            row.stage = profile.stage
            row.answers = dict(profile.answers)
            row.setup_completed_at = profile.setup_completed_at
            row.lock_version = expected_lock + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _profile(row)

    async def get_words(self, student_id: UUID) -> WordsState | None:
        """Return the words state, if it exists."""
        row = await self._s.get(ProfileWordsRow, student_id)
        return _words(row) if row else None

    async def save_words(
        self, state: WordsState, expected_lock: int | None, *, history: bool
    ) -> WordsState:
        """Insert or update; `history` also stores the set in the history."""
        payload = {"items": state.candidates}
        if expected_lock is None:
            row = ProfileWordsRow(
                student_id=state.student_id,
                words=list(state.words),
                candidates=payload,
                source=state.source,
                version=state.version,
                confirmed_at=state.confirmed_at,
                lock_version=0,
            )
            self._s.add(row)
        else:
            found = await self._s.get(
                ProfileWordsRow, state.student_id, with_for_update=True
            )
            if found is None or found.lock_version != expected_lock:
                raise AdmissionConflictError()
            row = found
            row.words = list(state.words)
            row.candidates = payload
            row.source = state.source
            row.version = state.version
            row.confirmed_at = state.confirmed_at
            row.lock_version = expected_lock + 1
        if history:
            self._s.add(
                ProfileWordsHistoryRow(
                    student_id=state.student_id,
                    version=state.version,
                    words=list(state.words),
                    confirmed_at=state.confirmed_at,
                )
            )
        await self._s.flush()
        await self._s.refresh(row)
        return _words(row)


class SqlReviewRepository:
    """Cached AI reviews."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def find(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> ReviewRecord | None:
        """Return the review of exactly this input."""
        row = await self._s.scalar(
            select(ReviewRow).where(
                ReviewRow.target_kind == target_kind,
                ReviewRow.target_id == target_id,
                ReviewRow.input_hash == input_hash,
                ReviewRow.status == "ready",
            )
        )
        return _review(row) if row else None

    async def latest(self, student_id: UUID, target_kind: str) -> ReviewRecord | None:
        """Return the newest ready review of the kind."""
        row = await self._s.scalar(
            select(ReviewRow)
            .where(
                ReviewRow.student_id == student_id,
                ReviewRow.target_kind == target_kind,
                ReviewRow.status == "ready",
            )
            .order_by(ReviewRow.created_at.desc())
            .limit(1)
        )
        return _review(row) if row else None

    async def count_since(self, student_id: UUID, task: str, since: dt.datetime) -> int:
        """Count the student's reviews of a task made since `since`."""
        n = await self._s.scalar(
            select(func.count())
            .select_from(ReviewRow)
            .where(
                ReviewRow.student_id == student_id,
                ReviewRow.task == task,
                ReviewRow.created_at >= since,
            )
        )
        return int(n or 0)

    async def add(self, review: ReviewRecord) -> ReviewRecord:
        """Insert the review."""
        row = ReviewRow(
            id=new_id(),
            student_id=review.student_id,
            target_kind=review.target_kind,
            target_id=review.target_id,
            input_hash=review.input_hash,
            task=review.task,
            model=review.model,
            prompt_version=review.prompt_version,
            rubric_version=review.rubric_version,
            schema_version=review.schema_version,
            words_version=review.words_version,
            grades=review.grades,
            overall=review.overall,
            payload=review.payload,
            safety_flag=review.safety_flag,
            status=review.status,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _review(row)
