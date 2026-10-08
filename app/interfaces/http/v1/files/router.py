"""Routes of the files area: /v1/files/* and /v1/me/files, /v1/me/storage."""

from app.interfaces.http.v1.files.handlers.complete_upload import complete_upload
from app.interfaces.http.v1.files.handlers.delete_file import delete_file
from app.interfaces.http.v1.files.handlers.get_download_url import get_download_url
from app.interfaces.http.v1.files.handlers.get_file import get_file
from app.interfaces.http.v1.files.handlers.get_storage import get_storage
from app.interfaces.http.v1.files.handlers.list_my_files import list_my_files
from app.interfaces.http.v1.files.handlers.rename_file import rename_file
from app.interfaces.http.v1.files.handlers.request_upload import request_upload
from app.interfaces.http.v1.files.schemas import (
    DeleteFileResponse,
    DownloadUrlResponse,
    FileItem,
    StorageResponse,
    UploadResponse,
)
from app.shared.pagination import Page

from fastapi import APIRouter

files_router = APIRouter(prefix="/v1/files", tags=["files"])
me_files_router = APIRouter(prefix="/v1/me", tags=["files"])

files_router.add_api_route(
    "",
    request_upload,
    methods=["POST"],
    status_code=201,
    response_model=UploadResponse,
)
files_router.add_api_route(
    "/{file_id}/complete", complete_upload, methods=["POST"], response_model=FileItem
)
files_router.add_api_route(
    "/{file_id}/url",
    get_download_url,
    methods=["GET"],
    response_model=DownloadUrlResponse,
)
files_router.add_api_route(
    "/{file_id}", get_file, methods=["GET"], response_model=FileItem
)
files_router.add_api_route(
    "/{file_id}", rename_file, methods=["PATCH"], response_model=FileItem
)
files_router.add_api_route(
    "/{file_id}", delete_file, methods=["DELETE"], response_model=DeleteFileResponse
)
me_files_router.add_api_route(
    "/files", list_my_files, methods=["GET"], response_model=Page[FileItem]
)
me_files_router.add_api_route(
    "/storage", get_storage, methods=["GET"], response_model=StorageResponse
)
