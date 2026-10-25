"""Email sent from the platform (`POST /v1/me/outbound-mail`)."""

from app.interfaces.http.v1.outbound_mail.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
