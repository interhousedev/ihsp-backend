"""Routes of the LMS learning side (catalog, enrollment, attempts, review)."""

from app.interfaces.http.v1.lms_learning.handlers.enroll import enroll
from app.interfaces.http.v1.lms_learning.handlers.get_attempt import get_attempt
from app.interfaces.http.v1.lms_learning.handlers.get_course import get_course
from app.interfaces.http.v1.lms_learning.handlers.get_course_landing import (
    get_course_landing,
)
from app.interfaces.http.v1.lms_learning.handlers.get_step import get_step
from app.interfaces.http.v1.lms_learning.handlers.get_video_stream import (
    get_video_stream,
)
from app.interfaces.http.v1.lms_learning.handlers.h5p import (
    answer_interaction,
    get_h5p_file,
    get_h5p_launch,
    record_h5p_result,
)
from app.interfaces.http.v1.lms_learning.handlers.join import join
from app.interfaces.http.v1.lms_learning.handlers.list_courses import list_courses
from app.interfaces.http.v1.lms_learning.handlers.list_my_courses import (
    list_my_courses,
)
from app.interfaces.http.v1.lms_learning.handlers.list_students import list_students
from app.interfaces.http.v1.lms_learning.handlers.mark_viewed import mark_viewed
from app.interfaces.http.v1.lms_learning.handlers.next_card import next_card
from app.interfaces.http.v1.lms_learning.handlers.override_attempt import (
    override_attempt,
)
from app.interfaces.http.v1.lms_learning.handlers.review_card import review_card
from app.interfaces.http.v1.lms_learning.handlers.save_answers import save_answers
from app.interfaces.http.v1.lms_learning.handlers.start_attempt import start_attempt
from app.interfaces.http.v1.lms_learning.handlers.submit_attempt import submit_attempt

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms", tags=["lms"])

router.add_api_route("/courses", list_courses, methods=["GET"])
router.add_api_route("/my-courses", list_my_courses, methods=["GET"])
router.add_api_route("/courses/{slug}", get_course, methods=["GET"])
router.add_api_route("/courses/{slug}/landing", get_course_landing, methods=["GET"])
router.add_api_route("/courses/{course_id}/enroll", enroll, methods=["POST"])
router.add_api_route("/join", join, methods=["POST"])
router.add_api_route("/courses/{course_id}/steps/{step_id}", get_step, methods=["GET"])
router.add_api_route(
    "/courses/{course_id}/steps/{step_id}/blocks/{block_id}/video",
    get_video_stream,
    methods=["GET"],
)
router.add_api_route("/steps/{step_id}/viewed", mark_viewed, methods=["POST"])
router.add_api_route(
    "/steps/{step_id}/blocks/{block_id}/attempts", start_attempt, methods=["POST"]
)
router.add_api_route("/attempts/{attempt_id}/answers", save_answers, methods=["PUT"])
router.add_api_route("/attempts/{attempt_id}/submit", submit_attempt, methods=["POST"])
router.add_api_route(
    "/steps/{step_id}/cards/{card_id}/review", review_card, methods=["POST"]
)
router.add_api_route("/steps/{step_id}/cards/next", next_card, methods=["GET"])
router.add_api_route("/courses/{course_id}/students", list_students, methods=["GET"])
router.add_api_route("/attempts/{attempt_id}", get_attempt, methods=["GET"])
router.add_api_route(
    "/attempts/{attempt_id}/override", override_attempt, methods=["POST"]
)
router.add_api_route(
    "/courses/{course_id}/steps/{step_id}/blocks/{block_id}/h5p",
    get_h5p_launch,
    methods=["GET"],
)
router.add_api_route(
    "/steps/{step_id}/blocks/{block_id}/h5p-result",
    record_h5p_result,
    methods=["POST"],
)
router.add_api_route(
    "/steps/{step_id}/blocks/{block_id}/interactions/{interaction_id}/answer",
    answer_interaction,
    methods=["POST"],
)
router.add_api_route(
    "/h5p/{token}/{path:path}",
    get_h5p_file,
    methods=["GET"],
    include_in_schema=False,
)
