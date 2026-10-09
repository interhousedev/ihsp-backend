"""Routes of the notebooks area: notebooks."""

from app.interfaces.http.v1.notebooks.handlers import (
    copy_notebook,
    create_notebook,
    delete_notebook,
    find_lesson_notebook,
    find_subject_notebook,
    get_notebook,
    get_notebook_usage,
    get_usage,
    list_course_steps,
    list_notebooks,
    open_course_workspace,
    open_lesson_notebook,
    open_subject_notebook,
    update_auto_settings,
    update_notebook,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])

router.add_api_route("", list_notebooks.list_notebooks, methods=["GET"])
router.add_api_route(
    "",
    create_notebook.create_notebook,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
# Before `/{notebook_id}`, or "usage" would be read as a notebook id.
router.add_api_route("/usage", get_usage.get_usage, methods=["GET"])
# The shared notebook of an LMS course's staff (get-or-create).
router.add_api_route(
    "/course-workspaces",
    open_course_workspace.open_course_workspace,
    methods=["POST"],
)
# Subject and lesson notebooks the system keeps up to date (get-or-create, lookup).
router.add_api_route(
    "/auto/subject/{subject_id}",
    open_subject_notebook.open_subject_notebook,
    methods=["POST"],
)
router.add_api_route(
    "/auto/subject/{subject_id}",
    find_subject_notebook.find_subject_notebook,
    methods=["GET"],
)
router.add_api_route(
    "/auto/lesson/{lesson_id}",
    open_lesson_notebook.open_lesson_notebook,
    methods=["POST"],
)
router.add_api_route(
    "/auto/lesson/{lesson_id}",
    find_lesson_notebook.find_lesson_notebook,
    methods=["GET"],
)
router.add_api_route("/{notebook_id}", get_notebook.get_notebook, methods=["GET"])
router.add_api_route(
    "/{notebook_id}/usage", get_notebook_usage.get_notebook_usage, methods=["GET"]
)
router.add_api_route(
    "/{notebook_id}/course-steps",
    list_course_steps.list_course_steps,
    methods=["GET"],
)
router.add_api_route(
    "/{notebook_id}/auto", update_auto_settings.update_auto_settings, methods=["PATCH"]
)
router.add_api_route(
    "/{notebook_id}/copy",
    copy_notebook.copy_notebook,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/{notebook_id}", update_notebook.update_notebook, methods=["PATCH"]
)
router.add_api_route(
    "/{notebook_id}",
    delete_notebook.delete_notebook,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
