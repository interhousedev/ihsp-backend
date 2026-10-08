"""Argument types shared by tools (descriptions are shown to AI clients)."""

from datetime import date
from typing import Annotated

from pydantic import Field

DateFromParam = Annotated[
    date | None, Field(description="First day, YYYY-MM-DD, inclusive.")
]
DateToParam = Annotated[
    date | None, Field(description="Last day, YYYY-MM-DD, inclusive.")
]
SemesterParam = Annotated[
    int | None,
    Field(ge=1, le=12, description="Semester number; the current one if omitted."),
]
