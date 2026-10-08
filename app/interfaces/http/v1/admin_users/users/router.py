"""Routes /v1/admin/users*."""

from app.interfaces.http.v1.admin_users.schemas import (
    AdminUserDetailResponse,
    AdminUserResponse,
)
from app.interfaces.http.v1.admin_users.users.handlers.get_user import get_user
from app.interfaces.http.v1.admin_users.users.handlers.get_users import get_users
from app.interfaces.http.v1.admin_users.users.handlers.post_block import post_block
from app.interfaces.http.v1.admin_users.users.handlers.post_mail_resume import (
    post_mail_resume,
)
from app.interfaces.http.v1.admin_users.users.handlers.post_mail_suspend import (
    post_mail_suspend,
)
from app.interfaces.http.v1.admin_users.users.handlers.post_reset_otp import (
    post_reset_otp,
)
from app.interfaces.http.v1.admin_users.users.handlers.post_reset_password import (
    post_reset_password,
)
from app.interfaces.http.v1.admin_users.users.handlers.post_revoke_sessions import (
    post_revoke_sessions,
)
from app.interfaces.http.v1.admin_users.users.handlers.post_roles import post_roles
from app.interfaces.http.v1.admin_users.users.handlers.post_unblock import (
    post_unblock,
)
from app.interfaces.http.v1.admin_users.users.schemas import ActivationUrlResponse
from app.shared.pagination import Page

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/admin/users", tags=["admin-users"])

router.add_api_route(
    "", get_users, methods=["GET"], response_model=Page[AdminUserResponse]
)
router.add_api_route(
    "/{id}", get_user, methods=["GET"], response_model=AdminUserDetailResponse
)
router.add_api_route(
    "/{id}/block", post_block, methods=["POST"], response_model=AdminUserResponse
)
router.add_api_route(
    "/{id}/unblock", post_unblock, methods=["POST"], response_model=AdminUserResponse
)
router.add_api_route(
    "/{id}/roles", post_roles, methods=["POST"], response_model=AdminUserResponse
)
router.add_api_route(
    "/{id}/sessions/revoke",
    post_revoke_sessions,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/{id}/reset-password",
    post_reset_password,
    methods=["POST"],
    response_model=ActivationUrlResponse,
)
router.add_api_route(
    "/{id}/reset-otp",
    post_reset_otp,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/{id}/mail/suspend",
    post_mail_suspend,
    methods=["POST"],
    response_model=AdminUserResponse,
)
router.add_api_route(
    "/{id}/mail/resume",
    post_mail_resume,
    methods=["POST"],
    response_model=AdminUserResponse,
)
