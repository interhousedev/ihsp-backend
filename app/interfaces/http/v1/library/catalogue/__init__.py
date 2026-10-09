"""Routes of the library catalogue area (items, files, text, subjects, books)."""

from app.interfaces.http.v1.library.catalogue.router_books import router as books
from app.interfaces.http.v1.library.catalogue.router_items import router as items

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [items, books]
