"""Response models of the admin attendance endpoints."""

from app.interfaces.http.v1.me_classwork.schemas import (
    LessonItemResponse,
    PersonRefResponse,
)

from pydantic import BaseModel


class MissingAttendanceResponse(BaseModel):
    """A teacher and the lessons without submitted attendance."""

    teacher: PersonRefResponse
    lessons: list[LessonItemResponse]
