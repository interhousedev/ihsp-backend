"""LMS engagement routes: XP, streak, daily review, mastery and class quests."""

from app.interfaces.http.v1.lms_engagement.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
