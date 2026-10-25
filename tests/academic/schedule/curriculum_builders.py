"""A small EMIS curriculum for the curriculum tests."""

import datetime as dt

from app.shared.contracts.emis import (
    EmisCurriculum,
    EmisCurriculumItem,
    EmisCurriculumSubject,
    EmisDirection,
    EmisName,
    EmisSemesterDates,
    EmisSemesterSubject,
)

D = dt.date.fromisoformat

MATH = 101
PHYSICS = 102
ENGLISH = 103
SEMESTERS = (
    EmisSemesterDates(1, D("2025-09-01"), D("2025-12-27")),
    EmisSemesterDates(2, D("2026-01-12"), D("2026-05-30")),
    EmisSemesterDates(3, D("2026-09-01"), D("2026-12-26")),
    EmisSemesterDates(4, D("2027-01-11"), D("2027-05-29")),
)

MATH_NAME = EmisName(uz="Matematika", ru="Математика", en="Mathematics")
PHYSICS_NAME = EmisName(uz="Fizika", ru="Физика", en="Physics")
ENGLISH_NAME = EmisName(uz="Ingliz tili", ru="", en="English")


def semester_subject(
    semester: int, emis_id: int, name: EmisName, *, hours: int = 68
) -> EmisSemesterSubject:
    """A subject of one semester with plausible hours."""
    return EmisSemesterSubject(
        semester_number=semester,
        emis_subject_id=emis_id,
        name=name,
        subject_type_id=2,
        study_hours=hours,
        class_hours=hours - 18,
        independent_hours=18,
        is_separated=emis_id == ENGLISH,
    )


def make_curriculum(
    *,
    semesters: tuple[EmisSemesterDates, ...] = SEMESTERS,
    semester_subjects: tuple[EmisSemesterSubject, ...] | None = None,
    emis_id: int = 2124,
) -> EmisCurriculum:
    """Four semesters, three subjects, one exam and one vocational subject."""
    if semester_subjects is None:
        semester_subjects = (
            semester_subject(3, MATH, MATH_NAME),
            semester_subject(3, PHYSICS, PHYSICS_NAME),
            semester_subject(3, ENGLISH, ENGLISH_NAME),
            semester_subject(4, MATH, MATH_NAME),
            semester_subject(4, PHYSICS, PHYSICS_NAME),
        )
    return EmisCurriculum(
        emis_id=emis_id,
        name="TN, MTN 2025-2027",
        direction=EmisDirection(312, "Umumiy o'rta ta'lim", "3010100"),
        speciality=EmisName(uz="Tabiiy fanlar", ru="Естественные науки", en=""),
        edu_form="Kunduzgi",
        language_code="uz",
        rating_min=0,
        rating_max=100,
        start_year=None,
        end_year=None,
        semesters_count=4,
        status="ACTIVE",
        semesters=semesters,
        subjects=(
            EmisCurriculumSubject(MATH, MATH_NAME, 2, 340),
            EmisCurriculumSubject(PHYSICS, PHYSICS_NAME, 2, 272),
            EmisCurriculumSubject(ENGLISH, ENGLISH_NAME, 1, 204),
        ),
        semester_subjects=semester_subjects,
        exams=(
            EmisCurriculumItem(7, EmisName(uz="Yakuniy imtihon", ru="", en=""), 12),
        ),
        vocational_subjects=(
            EmisCurriculumItem(9, EmisName(uz="", ru="Профессия", en=""), None),
        ),
    )
