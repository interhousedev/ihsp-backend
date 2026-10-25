"""Web search status route (`GET /v1/ai/web-search`)."""

from app.interfaces.http.v1.web_search.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
