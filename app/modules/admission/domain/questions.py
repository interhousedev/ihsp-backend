"""The background question set `admission_questions@1` (admit-ui §S2.1).

Question and option texts live in the web messages, keyed by the question id
and option id; the backend owns ids, kinds, options, visibility and limits.
"""

from dataclasses import dataclass
from typing import Final, Literal

QUESTION_SET_VERSION: Final = "admission_questions@1"

Section = Literal["about", "school", "tests", "goals", "where", "money", "wellbeing"]
QuestionKind = Literal[
    "single",
    "multi",
    "text",
    "number",
    "money",
    "range",
    "country",
    "combobox",
    "scale",
    "date",
    "switch",
    "repeat",
    "locked",
]
Sensitivity = Literal["normal", "finance", "wellbeing", "identity"]
Visibility = Literal["owner", "finance_read", "staff", "mentor"]
Origin = Literal["kollegio_policy", "kollegio_quiz", "own"]
Prefill = Literal["emis", "emis_locked", "academic_gpa", "default_uz", "default_on"]


@dataclass(frozen=True, slots=True)
class Question:
    """One question of the setup wizard."""

    id: str
    section: Section
    kind: QuestionKind
    required: bool
    options: tuple[str, ...] = ()
    max_length: int | None = None
    max_choices: int | None = None
    visible_if: str | None = None
    prefill_source: Prefill | None = None
    sensitivity: Sensitivity = "normal"
    visible_to: Visibility = "mentor"
    origin: Origin = "own"
    enabled: bool = True


def _q(
    n: int, section: Section, kind: QuestionKind, *, required: bool = True, **kw: object
) -> Question:
    """Build question `qNN`."""
    return Question(
        f"q{n:02d}", section, kind, required, **kw  # type: ignore[arg-type]
    )


YES_NO_APPLYING: Final = ("yes", "no", "applying")
GRADES: Final = ("grade_10", "grade_11", "graduated", "gap_year")
ARCHETYPES: Final = ("academics", "campus_life", "new_experiences", "everything")
STUDY_LEVELS: Final = ("bachelor", "foundation", "two_plus_two")
LANGUAGES: Final = ("en", "de", "ru", "tr", "ko", "ja", "zh", "it", "fr", "uz")
CITY_TYPES: Final = ("big_city", "college_town", "campus", "small_city", "any")
SIZES: Final = ("small", "medium", "large", "any")
CLIMATES: Final = ("warm", "mild", "cold", "any")
DISTANCES: Final = ("near", "medium", "far", "any")
WORK_VISA: Final = ("important", "nice", "not_important")
BUDGET_BANDS: Final = (
    "under_5k",
    "5k_15k",
    "15k_30k",
    "30k_50k",
    "over_50k",
)
AID_NEED: Final = ("none", "partial", "full")
SCHOLARSHIP_BASIS: Final = ("merit", "need", "government", "sports", "work_study")
FEE_WAIVER: Final = ("can_pay", "need_waiver", "not_sure")
FACILITIES: Final = ("halal_food", "prayer_room", "community")
GENDERS: Final = ("female", "male")
ENGLISH_TESTS: Final = ("ielts", "toefl", "duolingo", "sat_erw", "none", "planned")
SAT_ACT: Final = ("taken", "planned", "not_planning")
OTHER_TESTS: Final = ("ap", "a_level", "subject", "nuet", "dtm")
SUBJECTS: Final = (
    "math",
    "physics",
    "chemistry",
    "biology",
    "informatics",
    "english",
    "history",
    "geography",
    "literature",
    "economics",
)

QUESTIONS: Final[tuple[Question, ...]] = (
    _q(
        1,
        "about",
        "text",
        max_length=100,
        prefill_source="emis",
        sensitivity="identity",
        visible_to="staff",
    ),
    _q(
        2,
        "about",
        "date",
        prefill_source="emis_locked",
        sensitivity="identity",
        visible_to="staff",
        origin="kollegio_policy",
    ),
    _q(
        3,
        "about",
        "single",
        required=False,
        options=GENDERS,
        prefill_source="emis",
        sensitivity="identity",
        visible_to="staff",
    ),
    _q(
        4,
        "about",
        "country",
        prefill_source="default_uz",
        max_choices=3,
        sensitivity="identity",
        visible_to="staff",
    ),
    _q(6, "about", "single", options=YES_NO_APPLYING, visible_to="staff"),
    _q(7, "about", "repeat", options=LANGUAGES),
    _q(
        8,
        "school",
        "single",
        options=GRADES,
        prefill_source="emis",
        origin="kollegio_policy",
    ),
    _q(9, "school", "locked", prefill_source="emis_locked", origin="kollegio_policy"),
    _q(10, "school", "number", prefill_source="academic_gpa", origin="kollegio_policy"),
    _q(11, "school", "number", required=False, origin="kollegio_policy"),
    _q(12, "school", "multi", required=False, options=SUBJECTS, max_choices=3),
    _q(13, "school", "single", required=False, options=("yes", "no")),
    _q(14, "tests", "repeat", options=ENGLISH_TESTS, origin="kollegio_policy"),
    _q(15, "tests", "repeat", options=SAT_ACT, origin="kollegio_policy"),
    _q(16, "tests", "repeat", required=False, options=OTHER_TESTS),
    _q(17, "goals", "single", options=ARCHETYPES, origin="kollegio_quiz"),
    _q(18, "goals", "combobox", max_choices=3, origin="kollegio_quiz"),
    _q(19, "goals", "combobox", required=False, max_choices=3),
    _q(20, "goals", "text", required=False, max_length=200),
    _q(21, "goals", "text", required=False, max_length=200),
    _q(22, "goals", "text", required=False, max_length=300),
    _q(23, "goals", "text", required=False, max_length=300),
    _q(24, "where", "country", max_choices=10, origin="kollegio_quiz"),
    _q(25, "where", "multi", options=STUDY_LEVELS, origin="kollegio_quiz"),
    _q(26, "where", "multi", options=LANGUAGES),
    _q(27, "where", "single", options=CITY_TYPES, origin="kollegio_quiz"),
    _q(28, "where", "single", required=False, options=SIZES, origin="kollegio_quiz"),
    _q(
        29,
        "where",
        "single",
        required=False,
        options=tuple(dict.fromkeys(CLIMATES + DISTANCES)),
    ),
    _q(30, "where", "switch", prefill_source="default_on"),
    _q(31, "where", "single", required=False, options=WORK_VISA),
    _q(
        32,
        "money",
        "money",
        options=BUDGET_BANDS,
        sensitivity="finance",
        visible_to="finance_read",
        origin="kollegio_policy",
    ),
    _q(
        33,
        "money",
        "single",
        options=AID_NEED,
        sensitivity="finance",
        visible_to="finance_read",
        origin="kollegio_policy",
    ),
    _q(
        34,
        "money",
        "multi",
        required=False,
        options=SCHOLARSHIP_BASIS,
        sensitivity="finance",
        visible_to="staff",
    ),
    _q(
        35,
        "money",
        "single",
        options=FEE_WAIVER,
        sensitivity="finance",
        visible_to="finance_read",
    ),
    _q(
        36,
        "wellbeing",
        "multi",
        required=False,
        options=FACILITIES,
        sensitivity="wellbeing",
        visible_to="staff",
        enabled=False,
    ),
    _q(
        37,
        "wellbeing",
        "text",
        required=False,
        max_length=300,
        sensitivity="wellbeing",
        visible_to="staff",
        enabled=False,
    ),
    _q(
        38,
        "goals",
        "switch",
        required=False,
        visible_if="account_kind=alumni",
        visible_to="owner",
    ),
)

BY_ID: Final = {q.id: q for q in QUESTIONS}


def question(question_id: str) -> Question | None:
    """Return the question by id, or None."""
    return BY_ID.get(question_id)


def visible_questions(*, alumni: bool) -> tuple[Question, ...]:
    """Return the enabled questions visible to this student."""
    return tuple(
        q
        for q in QUESTIONS
        if q.enabled
        and (q.visible_if is None or (alumni and q.visible_if.endswith("alumni")))
    )


def hidden_from_mentors(question_id: str) -> bool:
    """Return whether mentors and helpers must not see the answer (#32–#37)."""
    q = BY_ID.get(question_id)
    return q is not None and q.visible_to in {"finance_read", "staff", "owner"}
