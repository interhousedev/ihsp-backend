"""LMS learning routes (B13); I1 collects `ROUTERS` per process."""

from app.interfaces.http.v1.lms_learning.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
