"""Admin routes of the academic schedule (B3)."""

from app.interfaces.http.v1.admin_schedule.groups.router import router as groups
from app.interfaces.http.v1.admin_schedule.lessons.router import router as lessons
from app.interfaces.http.v1.admin_schedule.rooms.router import router as rooms
from app.interfaces.http.v1.admin_schedule.students.router import router as students
from app.interfaces.http.v1.admin_schedule.subjects.router import router as subjects
from app.interfaces.http.v1.admin_schedule.terms.router import router as terms
from app.interfaces.http.v1.admin_schedule.timetable.router import router as timetable

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    terms,
    groups,
    subjects,
    rooms,
    timetable,
    lessons,
    students,
]
