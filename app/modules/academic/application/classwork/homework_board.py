"""Use case: the teacher's homework board of one subject and audience.

Every lesson of the journal option in the window, newest first, with the EMIS topic
and homework file, the teacher's homework, the two switches and the submission
counts.
"""

import datetime as dt
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.application.classwork.get_journal import (
    parse_audience_key,
)
from app.modules.academic.application.classwork.homework_settings import (
    settings_json,
)
from app.modules.academic.application.classwork.journal_options import (
    audience_key_of,
    audience_label,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.resource_items import (
    homework_refs,
    staff_resource_items,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.domain.classwork.errors import JournalNotFoundError
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.records import (
    JournalOption,
    SubmissionRecord,
)
from app.modules.academic.domain.classwork.review_rules import notify_effective
from app.modules.academic.domain.classwork.submission_rules import submission_status
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.links import LinksApi

BoardFilter = Literal["all", "with_homework", "to_review"]
MAX_LESSONS = 120


def submission_counts(
    lesson: Lesson, records: list[SubmissionRecord], total: int
) -> dict[str, int]:
    """``{submitted, late, missing, to_review, graded, total}`` of one lesson."""
    counts = {"submitted": 0, "late": 0, "to_review": 0, "graded": 0}
    for record in records:
        counts[submission_status(record.submitted_at, lesson.homework_due_date)] += 1
        if record.review_status == "pending":
            counts["to_review"] += 1
        elif record.review_status == "graded":
            counts["graded"] += 1
    total = max(total, len(records))
    return {**counts, "missing": total - len(records), "total": total}


class HomeworkBoard:
    """The lessons of one journal option with their homework and submissions."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        roster_loader: RosterLoader,
        links: LinksApi,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.roster_loader = roster_loader
        self.links = links

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        audience_key: str,
        *,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        only: BoardFilter = "all",
    ) -> dict[str, Any]:
        """Return ``StaffHomeworkBoard``.

        The window defaults to the current term; teachers see their own lessons of
        an option they teach, administrators every lesson of the option.

        Raises:
            JournalNotFoundError: No current term, a bad ``audience_key`` or an
                option the teacher does not teach.
        """
        keys = parse_audience_key(audience_key)
        today = local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        admin = actor.has(Role.ADMIN)
        async with self.uow_factory() as uow:
            term = await uow.results.current_term(today)
            if term is None:
                raise JournalNotFoundError(params={"audience_key": audience_key})
            start = date_from or term.starts_on
            end = date_to or term.ends_on
            options = await uow.journal.options(
                actor.user_id, term.starts_on, term.ends_on
            )
            matched = next(
                (
                    o
                    for o in options
                    if o.subject_id == subject_id and tuple(sorted(o.audience)) == keys
                ),
                None,
            )
            if matched is None and not admin:
                raise JournalNotFoundError(params={"audience_key": audience_key})
            lessons = [
                lesson
                for lesson in await uow.journal.lessons(subject_id, keys, start, end)
                if admin or lesson.is_taught_by(actor.user_id)
            ]
            lessons.sort(key=lambda lesson: (lesson.date, lesson.period), reverse=True)
            with_homework = [lesson for lesson in lessons if lesson.has_homework]
            submissions = await uow.submissions.for_lessons(
                [lesson.id for lesson in with_homework]
            )
            if only == "with_homework":
                lessons = with_homework
            elif only == "to_review":
                lessons = [
                    lesson
                    for lesson in with_homework
                    if any(
                        r.review_status == "pending"
                        for r in submissions.get(lesson.id, [])
                    )
                ]
            lessons = lessons[:MAX_LESSONS]
            saved = {
                uid for lesson in lessons for uid in lesson.attendance_roster or ()
            }
            roster = await self.roster_loader.load_for_keys(uow, keys, saved)
            settings = await uow.homework_settings.get(actor.user_id)
            teacher_ids = {
                lesson.teacher_id for lesson in lessons if lesson.teacher_id
            } - {actor.user_id}
            teacher_settings = {
                tid: await uow.homework_settings.get(tid) for tid in teacher_ids
            }
            teacher_settings[actor.user_id] = settings
        emis_ids = [
            lesson.id for lesson in lessons if lesson.emis_homework_url is not None
        ]
        resources = await self.links.resources_for_lessons(emis_ids) if emis_ids else {}
        total = len(roster.expected)
        items = []
        for lesson in lessons:
            teacher = (
                teacher_settings.get(lesson.teacher_id) if lesson.teacher_id else None
            )
            items.append(
                {
                    "lesson_id": str(lesson.id),
                    "date": lesson.date.isoformat(),
                    "period": lesson.period,
                    "topic": lesson.topic,
                    "emis_topic_description": lesson.emis_topic_description,
                    "emis_files": await staff_resource_items(
                        homework_refs(resources.get(lesson.id, [])), self.people
                    ),
                    "homework": (
                        {
                            "text": lesson.homework_text or "",
                            "due_date": (
                                lesson.homework_due_date.isoformat()
                                if lesson.homework_due_date
                                else None
                            ),
                            "due_auto": lesson.homework_due_auto,
                            "source": lesson.homework_source,
                        }
                        if lesson.has_homework
                        else None
                    ),
                    "accept_submissions": lesson.homework_accept_submissions,
                    "notify": lesson.homework_notify,
                    "notify_effective": notify_effective(
                        lesson.homework_notify,
                        teacher.notify_on_submission if teacher else True,
                    ),
                    "counts": (
                        submission_counts(lesson, submissions.get(lesson.id, []), total)
                        if lesson.has_homework
                        else None
                    ),
                }
            )
        return {
            "subject": _subject(matched, lessons, subject_id, locale),
            "audience_key": audience_key_of(keys),
            "label": (
                audience_label(matched)
                if matched is not None
                else audience_key_of(keys)
            ),
            "lessons": items,
            "settings": settings_json(settings),
        }


def _subject(
    option: JournalOption | None,
    lessons: list[Lesson],
    subject_id: UUID,
    locale: str,
) -> dict[str, Any]:
    """The board's ``SubjectRef``."""
    names: dict[str, str] = {}
    short: str | None = None
    if option is not None:
        names, short = option.subject_names, option.subject_short
    elif lessons:
        names, short = lessons[0].subject_names, lessons[0].subject_short
    name = localized(names, locale)
    return {"id": str(subject_id), "name": name, "short_name": short or name}
