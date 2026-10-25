"""Routes of the notebooks area: studio (outputs of a notebook, § 3.4)."""

from app.interfaces.http.v1.notebooks.handlers import (
    apply_artifact,
    apply_preview,
    attach_artifact,
    cancel_artifact,
    confirm_presentation_plan,
    create_artifact,
    create_presentation_plan,
    delete_artifact,
    download_artifact,
    edit_slides,
    exercise_feedback,
    get_artifact,
    get_presentation_plan,
    list_artifacts,
    rename_artifact,
    retry_artifact,
    revise_slides,
    save_as_source,
    save_flashcard_set,
    save_progress,
    save_to_files,
    update_presentation_plan,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])

_ONE = "/{notebook_id}/artifacts/{artifact_id}"
_PLANS = "/{notebook_id}/presentation-plans"
_PLAN = f"{_PLANS}/{{plan_id}}"

router.add_api_route(
    _PLANS,
    create_presentation_plan.create_presentation_plan,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    _PLAN, get_presentation_plan.get_presentation_plan, methods=["GET"]
)
router.add_api_route(
    _PLAN, update_presentation_plan.update_presentation_plan, methods=["PATCH"]
)
router.add_api_route(
    f"{_PLAN}/confirm",
    confirm_presentation_plan.confirm_presentation_plan,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)

router.add_api_route(
    "/{notebook_id}/artifacts", list_artifacts.list_artifacts, methods=["GET"]
)
router.add_api_route(
    "/{notebook_id}/artifacts",
    create_artifact.create_artifact,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(_ONE, get_artifact.get_artifact, methods=["GET"])
router.add_api_route(_ONE, rename_artifact.rename_artifact, methods=["PATCH"])
router.add_api_route(
    _ONE,
    delete_artifact.delete_artifact,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    f"{_ONE}/cancel", cancel_artifact.cancel_artifact, methods=["POST"]
)
router.add_api_route(
    f"{_ONE}/retry",
    retry_artifact.retry_artifact,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    f"{_ONE}/progress",
    save_progress.save_progress,
    methods=["PUT"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    f"{_ONE}/exercise-feedback",
    exercise_feedback.exercise_feedback,
    methods=["POST"],
)
router.add_api_route(
    f"{_ONE}/save-as-source",
    save_as_source.save_as_source,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    f"{_ONE}/save-to-files",
    save_to_files.save_to_files,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    f"{_ONE}/attach-to-lesson",
    attach_artifact.attach_artifact,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    f"{_ONE}/flashcard-set", save_flashcard_set.save_flashcard_set, methods=["POST"]
)
router.add_api_route(f"{_ONE}/slides", edit_slides.edit_slides, methods=["PUT"])
router.add_api_route(
    f"{_ONE}/slides/revise",
    revise_slides.revise_slides,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    f"{_ONE}/apply-preview", apply_preview.apply_preview, methods=["POST"]
)
router.add_api_route(f"{_ONE}/apply", apply_artifact.apply_artifact, methods=["POST"])
router.add_api_route(
    f"{_ONE}/download",
    download_artifact.download_artifact,
    methods=["GET"],
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
