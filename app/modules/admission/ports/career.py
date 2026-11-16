"""Port: the career inventory, the majors taxonomy and the students' plans."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.career import CareerMajor, CareerPlan, CareerQuestion


class CareerRepository(Protocol):
    """Inventory questions, majors and one career plan per student."""

    async def questions(self, *, active_only: bool) -> list[CareerQuestion]:
        """Return the questions by section and sort order."""
        ...

    async def get_question(self, question_id: UUID) -> CareerQuestion | None:
        """Return one question."""
        ...

    async def save_question(self, question: CareerQuestion) -> CareerQuestion:
        """Insert or update a question."""
        ...

    async def majors(self, *, active_only: bool) -> list[CareerMajor]:
        """Return the majors by area and sort order."""
        ...

    async def get_major(self, major_id: UUID) -> CareerMajor | None:
        """Return one major."""
        ...

    async def save_major(self, major: CareerMajor) -> CareerMajor:
        """Insert or update a major (the code is unique → conflict)."""
        ...

    async def plan(self, student_id: UUID) -> CareerPlan | None:
        """Return the student's plan."""
        ...

    async def save_plan(self, plan: CareerPlan) -> CareerPlan:
        """Insert or store the plan (compare-and-set on `lock_version`)."""
        ...
