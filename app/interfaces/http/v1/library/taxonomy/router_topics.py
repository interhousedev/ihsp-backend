"""Routes of topics: the public tree and the librarian's editor."""

from app.interfaces.http.v1.library.taxonomy.handlers import (
    create_topic,
    delete_topic,
    list_manage_topics,
    list_topics,
    update_topic,
)

from fastapi import APIRouter, status

router = APIRouter(tags=["library"])

router.add_api_route("/v1/library/topics", list_topics.list_topics, methods=["GET"])
router.add_api_route(
    "/v1/manage/library/topics", list_manage_topics.list_manage_topics, methods=["GET"]
)
router.add_api_route(
    "/v1/manage/library/topics",
    create_topic.create_topic,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/v1/manage/library/topics/{topic_id}", update_topic.update_topic, methods=["PATCH"]
)
router.add_api_route(
    "/v1/manage/library/topics/{topic_id}",
    delete_topic.delete_topic,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
