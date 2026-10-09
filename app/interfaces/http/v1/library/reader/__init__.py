"""Routes of the library reader area: shelf, progress, annotations, My library."""

from app.interfaces.http.v1.library.reader.router_plans import router as plans
from app.interfaces.http.v1.library.reader.router_reader import router as reader

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [reader, plans]
