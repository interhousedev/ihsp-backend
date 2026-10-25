"""Routes of the library taxonomy area: topics, collections, reading lists, stats."""

from app.interfaces.http.v1.library.taxonomy.router_collections import (
    router as collections,
)
from app.interfaces.http.v1.library.taxonomy.router_lists import router as lists
from app.interfaces.http.v1.library.taxonomy.router_topics import router as topics

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [topics, collections, lists]
