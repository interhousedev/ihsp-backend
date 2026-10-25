"""EMIS class-hours response (the bells of the lyceum)."""

from pydantic import BaseModel, Field


class ClassHourV1DTO(BaseModel):
    """One pair: ``pair_number`` is 0-based, times are ``HH:MM``."""

    pair_number: int
    begin_time: str
    end_time: str


class ClassHoursV1DTO(BaseModel):
    """The body of ``GET student-profiles/class-hours/`` (a ``results`` list)."""

    results: list[ClassHourV1DTO] = Field(default_factory=list)
