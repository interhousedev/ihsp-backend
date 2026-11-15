"""Public LMS routes: published courses read without signing in (`/v1/lms/public`)."""

from app.interfaces.http.v1.lms_public.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
