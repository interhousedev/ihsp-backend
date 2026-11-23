"""LMS AI review routes (the ai_review block); collected per process."""

from app.interfaces.http.v1.lms_ai_review.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
