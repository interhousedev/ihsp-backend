"""Flash card routes: sets, cards, study, review and copy (module B10)."""

from app.interfaces.http.v1.flashcards.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
