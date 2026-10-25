"""Files routes: uploads, downloads, My files and the quota (module B6)."""

from app.interfaces.http.v1.files.router import files_router, me_files_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [files_router, me_files_router]
