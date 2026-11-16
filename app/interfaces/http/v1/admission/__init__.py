"""Admission app routes (`/v1/admission/*`, guest links under `/v1/public/...`)."""

from app.interfaces.http.v1.admission import (
    routes_catalog_staff,
    routes_chooser,
    routes_documents,
    routes_goal_plan,
    routes_guest,
    routes_help,
    routes_items,
    routes_profile,
    routes_proofs,
    routes_staff,
)
from app.interfaces.http.v1.admission.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    router,
    routes_profile.router,
    routes_chooser.router,
    routes_proofs.router,
    routes_help.router,
    routes_guest.router,
    routes_staff.router,
    routes_documents.router,
    routes_items.router,
    routes_goal_plan.router,
    routes_catalog_staff.router,
]
