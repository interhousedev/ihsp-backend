"""Secret iCal feed (`GET /ical/{token}.ics`, WEB-6)."""

from app.interfaces.http.public.ical.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
