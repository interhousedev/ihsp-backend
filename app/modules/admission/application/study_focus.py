"""The student's field of study, read from every place it is stored.

Career is canonical: the plan's majors come first, then the career quiz answer
and the legacy setup answer, all mapped to catalog study-field ids.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from app.modules.admission.domain.study_fields import canonical_id, labels_of
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork

FIELDS_QUESTION: Final = "q18"
STUDY_FIELDS_ANSWER: Final = "study_fields"
CAREER_QUIZ: Final = "career"
UNKNOWN_PREFIX: Final = "x_"


@dataclass(frozen=True, slots=True)
class StudyFocus:
    """Catalog study-field ids and the chosen career majors (plan identifiers)."""

    field_ids: tuple[str, ...]
    major_ids: tuple[str, ...]

    @property
    def chosen(self) -> bool:
        """True when the student named any field or major."""
        return bool(self.field_ids or self.major_ids)

    def labels(self, locale: str = "en") -> tuple[str, ...]:
        """Display labels in the locale, in the order of `field_ids`."""
        return tuple(field_label(i, locale) for i in self.field_ids)


def field_label(field_id: str, locale: str = "en") -> str:
    """Label of a field id; an unknown spelling shows its slug as words."""
    raw = field_id.removeprefix(UNKNOWN_PREFIX).replace("_", " ")
    return labels_of(field_id, raw, locale)


def _texts(value: Any) -> list[str]:
    """Strings of a free-text or multi-choice answer."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _ids(value: Any) -> list[str]:
    """Catalog ids of the spellings in an answer."""
    return [canonical_id(t) for t in _texts(value)]


def _major_field(code: str, names: Iterable[str]) -> str | None:
    """Catalog id of a major from its code, then its names; None when unmapped."""
    for raw in (code, *names):
        found = canonical_id(raw)
        if not found.startswith(UNKNOWN_PREFIX):
            return found
    return None


async def load_study_focus(uow: AdmissionUnitOfWork, student_id: UUID) -> StudyFocus:
    """The single read model of what the student wants to study."""
    plan = await uow.career.plan(student_id)
    chosen = tuple(plan.majors) if plan is not None else ()
    ids: list[str] = []
    if chosen:
        taxonomy = {m.code: m for m in await uow.career.majors(active_only=False)}
        for code in chosen:
            major = taxonomy.get(code)
            if major is None:
                continue
            field = _major_field(major.code, major.name.values())
            if field is not None:
                ids.append(field)
    quiz = await uow.profile_details.get_quiz(student_id, CAREER_QUIZ)
    if quiz is not None:
        ids.extend(_ids(quiz.answers.get(STUDY_FIELDS_ANSWER)))
    profile = await uow.profiles.get(student_id)
    if profile is not None:
        ids.extend(_ids(profile.answers.get(FIELDS_QUESTION)))
    return StudyFocus(tuple(dict.fromkeys(ids)), chosen)
