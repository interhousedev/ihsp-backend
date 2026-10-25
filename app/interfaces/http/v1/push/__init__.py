"""Web Push routes: config for the browser and the caller's device subscriptions."""

from app.interfaces.http.v1.push.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
