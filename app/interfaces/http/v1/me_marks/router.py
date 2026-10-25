"""Routes of the student marks pages."""

from app.interfaces.http.v1.me_marks.handlers.get_day_grades import get_day_grades
from app.interfaces.http.v1.me_marks.handlers.get_grades import get_grades
from app.interfaces.http.v1.me_marks.handlers.get_my_group_progress import (
    get_my_group_progress,
)
from app.interfaces.http.v1.me_marks.handlers.get_planner import get_planner
from app.interfaces.http.v1.me_marks.handlers.get_record_book import get_record_book
from app.interfaces.http.v1.me_marks.handlers.get_subject import get_subject
from app.interfaces.http.v1.me_marks.handlers.list_lesson_results import (
    list_lesson_results,
)
from app.interfaces.http.v1.me_marks.handlers.list_subject_lessons import (
    list_subject_lessons,
)
from app.interfaces.http.v1.me_marks.handlers.list_subjects import list_subjects
from app.interfaces.http.v1.me_marks.planner_schemas import SubjectPlannerResponse
from app.interfaces.http.v1.me_marks.schemas import (
    DayGradesResponse,
    GroupProgressResponse,
    LessonResultRow,
    RecordBookResponse,
    SemesterGradesResponse,
    SubjectCardResponse,
    SubjectDetailResponse,
    SubjectLessonListResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me", tags=["marks"])

router.add_api_route(
    "/subjects",
    list_subjects,
    methods=["GET"],
    response_model=list[SubjectCardResponse],
)
router.add_api_route(
    "/subjects/{subject_id}",
    get_subject,
    methods=["GET"],
    response_model=SubjectDetailResponse,
)
router.add_api_route(
    "/subjects/{subject_id}/lessons",
    list_subject_lessons,
    methods=["GET"],
    response_model=SubjectLessonListResponse,
)
router.add_api_route(
    "/subjects/{subject_id}/planner",
    get_planner,
    methods=["GET"],
    response_model=SubjectPlannerResponse,
)
router.add_api_route(
    "/lesson-results",
    list_lesson_results,
    methods=["GET"],
    response_model=list[LessonResultRow],
)
router.add_api_route(
    "/grades", get_grades, methods=["GET"], response_model=SemesterGradesResponse
)
router.add_api_route(
    "/grades/day", get_day_grades, methods=["GET"], response_model=DayGradesResponse
)
router.add_api_route(
    "/record-book", get_record_book, methods=["GET"], response_model=RecordBookResponse
)
router.add_api_route(
    "/group/progress",
    get_my_group_progress,
    methods=["GET"],
    response_model=GroupProgressResponse,
)
