"""Collects a student's application for the full review.

Only data the student's mentors may also read goes in: profile answers of normal
sensitivity (never finance, wellbeing or identity), items,
courses, the list, documents and the checklist. Essays are the live drafts; the
review is marked staff-visible only when they equal the shared versions.
"""

from typing import Any
from uuid import UUID

from app.modules.admission.application.items import items_summary
from app.modules.admission.application.words import answer_texts
from app.modules.admission.ports.app_review import ReviewInputs
from app.modules.admission.ports.essays import EssayReader
from app.modules.admission.ports.unit_of_work import UowFactory

_TEXT_MAX = 4000


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


class UowReviewInputs:
    """Reads everything in one unit of work plus the essay reader."""

    def __init__(self, uow_factory: UowFactory, essays: EssayReader | None) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._essays = essays

    async def load(self, student_id: UUID) -> ReviewInputs:
        """Return the AI-safe view of the application."""
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
            words = await uow.items.words(student_id)
            items = await uow.items.list_for(student_id)
            metrics = await uow.items.metrics_for([i.id for i in items])
            courses = await uow.courses.list_for(student_id)
            entries = await uow.shortlist.entries(student_id)
            names = await uow.deadlines.institution_names(
                {e.institution_id for e in entries}
            )
            documents = await uow.documents.for_students([student_id])
            checklist = await uow.checklist.for_student(student_id)
        answers = [
            (f"answer:{qid}", f"{qid}: {text[:_TEXT_MAX]}")
            for qid, text in answer_texts(profile.answers if profile else {}).items()
        ]
        item_lines = [
            (f"item:{i['id']}", _text({k: v for k, v in i.items() if k != "id"}))
            for i in items_summary(items, metrics)
        ]
        course_lines = [
            (
                f"course:{c.id or n}",
                _text(
                    {
                        "title": c.title,
                        "provider": c.provider,
                        "level": c.level,
                        "year": c.year,
                        "grade": c.grade,
                    }
                ),
            )
            for n, c in enumerate(courses)
            if c.included
        ]
        uni_lines = [
            (
                f"entry:{e.id}",
                _text(
                    {
                        "university": names.get(e.institution_id, "unknown"),
                        "round": e.round,
                        "status": e.status,
                        "bucket": e.bucket or "unset",
                        "affordability": e.affordability_status,
                    }
                ),
            )
            for e in entries
        ]
        ready = [
            (
                f"document:{d.id}",
                f"document {d.kind}: review {d.review_status}, "
                f"versions {d.current_version}",
            )
            for d in documents
        ]
        ready += [
            (
                f"checklist:{c.id}",
                f"checklist {c.template_key}: {c.status}, due "
                f"{c.due_utc.date().isoformat() if c.due_utc else 'none'}"
                + (
                    f", for {_entry_name(names, entries, c.list_entry_id)}"
                    if c.list_entry_id
                    else ""
                ),
            )
            for c in checklist
        ]
        essays, staff_visible = await self._essay_lines(student_id)
        return ReviewInputs(
            words=tuple(words.words) if words else (),
            profile=answers,
            items=item_lines,
            essays=essays,
            courses=course_lines,
            universities=uni_lines,
            readiness=ready,
            staff_visible=staff_visible,
        )

    async def _essay_lines(
        self, student_id: UUID
    ) -> tuple[list[tuple[str, str]], bool]:
        if self._essays is None:
            return [], True
        live = await self._essays.latest_for(student_id)
        live = [e for e in live if e.body.strip()]
        if not live:
            return [], True
        shared = await self._essays.latest_for(student_id, shared_only=True)
        same = {(e.essay_id, e.body) for e in live} == {
            (e.essay_id, e.body) for e in shared if e.body.strip()
        }
        lines = [
            (
                f"essay:{e.essay_id}",
                f"{e.kind} '{e.title}' (prompt: {e.prompt_text or 'none'}; "
                f"{e.word_count} of {e.word_limit or 'no'} word limit):\n"
                f"{e.body[:_TEXT_MAX]}",
            )
            for e in live
        ]
        return lines, same


def _entry_name(names: dict[Any, str], entries: list[Any], entry_id: UUID) -> str:
    for e in entries:
        if e.id == entry_id:
            return names.get(e.institution_id, "")
    return ""
