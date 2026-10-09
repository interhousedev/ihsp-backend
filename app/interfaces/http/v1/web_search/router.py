"""Routes of web search outside a chat (`/v1/ai/web-search`)."""

from app.interfaces.http.v1.web_search.handlers import get_web_search

from fastapi import APIRouter

router = APIRouter(prefix="/v1/ai/web-search", tags=["ai"])

router.add_api_route("", get_web_search.get_web_search, methods=["GET"])
