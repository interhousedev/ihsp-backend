"""HTTP routes of course authoring (task B12)."""

from app.interfaces.http.v1.lms_authoring.courses.router import router as courses
from app.interfaces.http.v1.lms_authoring.creators.router import router as creators
from app.interfaces.http.v1.lms_authoring.draft.router import router as draft
from app.interfaces.http.v1.lms_authoring.preview.router import router as preview
from app.interfaces.http.v1.lms_authoring.publishing.router import router as publishing
from app.interfaces.http.v1.lms_authoring.staff.router import router as staff
from app.interfaces.http.v1.lms_authoring.steps.router import router as steps
from app.interfaces.http.v1.lms_authoring.versions.router import router as versions

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    courses,
    creators,
    draft,
    steps,
    publishing,
    versions,
    staff,
    preview,
]
