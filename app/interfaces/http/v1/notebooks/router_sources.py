"""Routes of the notebooks area: sources and passages."""

from app.interfaces.http.v1.notebooks.handlers import (
    add_sources,
    discover_sources,
    get_passage,
    get_source,
    list_passages,
    list_sources,
    remove_source,
    search_sources,
    select_sources,
    sync_source,
    update_source,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])

router.add_api_route(
    "/{notebook_id}/sources", list_sources.list_sources, methods=["GET"]
)
router.add_api_route(
    "/{notebook_id}/sources",
    add_sources.add_sources,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/{notebook_id}/discover", discover_sources.discover_sources, methods=["POST"]
)
router.add_api_route(
    "/{notebook_id}/search", search_sources.search_sources, methods=["GET"]
)
# Before `/sources/{source_id}`, or "select" would be read as a source id.
router.add_api_route(
    "/{notebook_id}/sources/select", select_sources.select_sources, methods=["POST"]
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}", get_source.get_source, methods=["GET"]
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}",
    update_source.update_source,
    methods=["PATCH"],
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}",
    remove_source.remove_source,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}/sync", sync_source.sync_source, methods=["POST"]
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}/passages",
    list_passages.list_passages,
    methods=["GET"],
)
router.add_api_route(
    "/{notebook_id}/passages/{passage_id}", get_passage.get_passage, methods=["GET"]
)
