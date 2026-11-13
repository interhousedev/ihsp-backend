"""Red diploma and medal eligibility of the student (record book marks)."""

from typing import Literal
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
)
from app.modules.academic.domain.marks import honours
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.grading import rounded_mark
from app.shared.actor import Actor
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisSource,
    EmisUnavailable,
)
from app.shared.contracts.honours import HonoursRules
from app.shared.contracts.identity import IdentityDirectory


class GetHonours:
    """Evaluates the honours rules over the stored semester and control marks."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        identity: IdentityDirectory,
        emis: EmisSource,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._emis = emis

    async def execute(
        self, actor: Actor, rules: HonoursRules
    ) -> tuple[list[honours.AwardResult], str | None]:
        """Return the awards and the school certificate serial from EMIS."""
        serial = await self._serial(actor)
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await uow.reader.results(actor.user_id, None)
            marks = await uow.reader.marks(actor.user_id)
            view = await build_context(
                uow.reader,
                self._identity,
                locale=locale,
                subject_ids={r.subject_id for r in results if r.subject_id},
            )
        controls: dict[
            tuple[int, UUID], list[tuple[Literal["midterm", "final"], int]]
        ] = {}
        for mark in marks:
            key = (mark.semester, mark.subject_id)
            if mark.type == "midterm":
                controls.setdefault(key, []).append(("midterm", int(mark.value)))
            elif mark.type == "final":
                controls.setdefault(key, []).append(("final", int(mark.value)))
        rows = [
            honours.SubjectSemesterMarks(
                subject_id=r.subject_id,
                subject_name=view.subject_name(r.subject_id),
                semester=r.semester,
                semester_mark=rounded_mark(r.value),
                controls=tuple(controls.get((r.semester, r.subject_id), ())),
            )
            for r in sorted(results, key=lambda r: r.semester)
            if r.subject_id is not None and r.value is not None
        ]
        return honours.evaluate(rules, rows, serial), serial

    async def _serial(self, actor: Actor) -> str | None:
        try:
            profile = await self._emis.profile(actor.user_id)
        except EmisCredentialsMissing:
            return None
        except EmisAuthFailed as exc:  # a 401 here would log the student out
            raise EmisUnavailable(support_details="EMIS login needs a refresh") from exc
        return profile.school_certificate_serial
