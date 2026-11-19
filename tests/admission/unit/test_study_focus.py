"""ADM-U6-SYNC: one read model of the field of study over plan, quiz and setup."""

from types import SimpleNamespace
from typing import Any

from app.modules.admission.application.study_focus import load_study_focus
from app.modules.admission.domain.career import CareerMajor, CareerPlan
from app.modules.admission.domain.profile import AdmissionProfile
from app.modules.admission.domain.profile_details import QuizAnswers
from app.modules.admission.domain.study_fields import canonical_id
from app.shared.ids import new_id

STUDENT = new_id()
CS = canonical_id("Computer Science")
BIO = canonical_id("Biology")
MAJORS = [
    CareerMajor(
        new_id(), "computer_science", "stem", {"en": "Computer Science", "ru": "a"}
    ),
    CareerMajor(new_id(), "zzqx_unmapped", "stem", {"en": "Zzqx Unmapped"}),
]


def _uow(
    majors: list[str] | None = None,
    quiz: Any = None,
    q18: Any = None,
) -> Any:
    plan = CareerPlan(STUDENT, majors=majors or []) if majors is not None else None
    profile = AdmissionProfile(STUDENT, answers={"q18": q18}) if q18 else None

    async def plan_of(_: Any) -> Any:
        return plan

    async def majors_of(active_only: bool = True) -> list[CareerMajor]:
        return MAJORS

    async def quiz_of(_: Any, __: str) -> Any:
        return QuizAnswers(STUDENT, "career", {"study_fields": quiz}) if quiz else None

    async def profile_of(_: Any) -> Any:
        return profile

    return SimpleNamespace(
        career=SimpleNamespace(plan=plan_of, majors=majors_of),
        profile_details=SimpleNamespace(get_quiz=quiz_of),
        profiles=SimpleNamespace(get=profile_of),
    )


async def test_empty_student_has_no_focus() -> None:
    """ADM-U6-SYNC-1: nothing stored means no field and nothing chosen."""
    focus = await load_study_focus(_uow(), STUDENT)
    assert focus.field_ids == ()
    assert not focus.chosen


async def test_career_major_maps_to_catalog_field() -> None:
    """ADM-U6-SYNC-2: a chosen major shows as its catalog field."""
    focus = await load_study_focus(_uow(majors=["computer_science"]), STUDENT)
    assert focus.field_ids == (CS,)
    assert focus.major_ids == ("computer_science",)
    assert focus.labels("en") == ("Computer Science",)


async def test_unmapped_major_is_chosen_but_adds_no_field() -> None:
    """ADM-U6-SYNC-3: an unmapped major counts as chosen without a field id."""
    focus = await load_study_focus(_uow(majors=["zzqx_unmapped"]), STUDENT)
    assert focus.field_ids == ()
    assert focus.chosen


async def test_union_is_deduped_in_stable_order() -> None:
    """ADM-U6-SYNC-4: plan, then quiz, then setup; duplicates collapse."""
    focus = await load_study_focus(
        _uow(
            majors=["computer_science"],
            quiz=["Biology", "Computer Science"],
            q18="Biology",
        ),
        STUDENT,
    )
    assert focus.field_ids == (CS, BIO)


async def test_quiz_and_setup_alone_count() -> None:
    """ADM-U6-SYNC-5: the quiz answer or the legacy answer alone is a focus."""
    assert (await load_study_focus(_uow(quiz=["Biology"]), STUDENT)).field_ids == (BIO,)
    assert (await load_study_focus(_uow(q18="Biology"), STUDENT)).field_ids == (BIO,)
