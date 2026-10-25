"""Certificates routes: types, a student's entries and files, staff views."""

from app.interfaces.http.v1.certificates.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
