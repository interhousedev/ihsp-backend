"""Login cues: admin pre-registration of EMIS logins (/v1/admin/login-cues)."""

from app.interfaces.http.v1.admin_users.login_cues.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
