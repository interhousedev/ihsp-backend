"""Routes of flash cards (`/v1/me/flashcard-sets*`, `/v1/me/flashcards/*`)."""

from app.interfaces.http.v1.flashcards.handlers import (
    copy_from_share,
    create_set,
    delete_set,
    get_set,
    list_sets,
    replace_cards,
    review_card,
    study_next,
    update_set,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/me", tags=["flashcards"])

router.add_api_route("/flashcard-sets", list_sets.list_sets, methods=["GET"])
router.add_api_route("/flashcard-sets", create_set.create_set, methods=["POST"])
router.add_api_route(
    "/flashcard-sets/copy", copy_from_share.copy_from_share, methods=["POST"]
)
router.add_api_route("/flashcard-sets/{set_id}", get_set.get_set, methods=["GET"])
router.add_api_route(
    "/flashcard-sets/{set_id}", update_set.update_set, methods=["PATCH"]
)
router.add_api_route(
    "/flashcard-sets/{set_id}",
    delete_set.delete_set,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/flashcard-sets/{set_id}/cards", replace_cards.replace_cards, methods=["PUT"]
)
router.add_api_route(
    "/flashcard-sets/{set_id}/study", study_next.study_next, methods=["GET"]
)
router.add_api_route(
    "/flashcards/{card_id}/review", review_card.review_card, methods=["POST"]
)
