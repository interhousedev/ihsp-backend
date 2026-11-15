"""Onboarding routes: the wizard a student sees after registration."""

from app.interfaces.http.v1.onboarding.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
