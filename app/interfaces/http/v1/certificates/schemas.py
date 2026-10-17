"""Request and response schemas of the certificates routes."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.modules.certificates.application.get_staff_ranking import RankedStudent
from app.modules.certificates.application.get_staff_stats import TypeStats
from app.modules.certificates.application.import_emis import ImportResult
from app.modules.certificates.application.list_staff_entries import (
    StaffEntriesPage,
    StaffEntryView,
)
from app.modules.certificates.application.staff_scope import StaffFilters
from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import CertificateEntry, EntryFile
from app.modules.certificates.ports.student_directory import GroupInfo

from pydantic import BaseModel, Field

Text = Field(min_length=1, max_length=120)


class TypeName(BaseModel):
    """A name in the three languages."""

    uz: str = Text
    ru: str = Text
    en: str = Text


class CertificateTypeInput(BaseModel):
    """Body of POST /admin/types."""

    code: str = Field(min_length=1, max_length=40)
    name: TypeName
    levels: list[str] = Field(default_factory=list, max_length=40)
    asks_level: bool = False
    asks_score: bool = False
    score_min: float | None = None
    score_max: float | None = None
    asks_percent: bool = False
    asks_subject: bool = False
    asks_year: bool = True
    position: int | None = Field(default=None, ge=0, le=10_000)


class CertificateTypePatch(BaseModel):
    """Body of PATCH /admin/types/{id}: only the sent fields change."""

    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: TypeName | None = None
    levels: list[str] | None = Field(default=None, max_length=40)
    asks_level: bool | None = None
    asks_score: bool | None = None
    score_min: float | None = None
    score_max: float | None = None
    asks_percent: bool | None = None
    asks_subject: bool | None = None
    asks_year: bool | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)


class CertificateTypeResponse(BaseModel):
    """CertificateType."""

    id: UUID
    code: str
    name: TypeName
    levels: list[str]
    asks_level: bool
    asks_score: bool
    score_min: float | None
    score_max: float | None
    asks_percent: bool
    asks_subject: bool
    asks_year: bool
    builtin: bool
    position: int

    @classmethod
    def from_domain(cls, kind: CertificateType) -> "CertificateTypeResponse":
        """Build the response from the domain type."""
        return cls(
            id=kind.id,
            code=kind.code,
            name=TypeName(
                uz=kind.name.get("uz", ""),
                ru=kind.name.get("ru", ""),
                en=kind.name.get("en", ""),
            ),
            levels=kind.levels,
            asks_level=kind.asks_level,
            asks_score=kind.asks_score,
            score_min=kind.score_min,
            score_max=kind.score_max,
            asks_percent=kind.asks_percent,
            asks_subject=kind.asks_subject,
            asks_year=kind.asks_year,
            builtin=kind.builtin,
            position=kind.position,
        )


class CertificateFileResponse(BaseModel):
    """CertificateFile."""

    id: UUID
    name: str
    size: int
    content_type: str

    @classmethod
    def from_domain(cls, file: EntryFile) -> "CertificateFileResponse":
        """Build the response from the domain file."""
        return cls(
            id=file.id, name=file.name, size=file.size, content_type=file.content_type
        )


class EntryValues(BaseModel):
    """Values a student fills in for a certificate."""

    level: str | None = Field(default=None, max_length=40)
    score: float | None = None
    percent: float | None = None
    subject: str | None = Field(default=None, max_length=255)
    year: int | None = None
    serial: str | None = Field(default=None, max_length=255)


class CreateEntryBody(EntryValues):
    """Body of POST /me."""

    type_id: UUID


class UpdateEntryBody(EntryValues):
    """Body of PATCH /me/{entry_id}: only the sent fields change."""


class CertificateEntryResponse(BaseModel):
    """CertificateEntry."""

    id: UUID
    type_id: UUID
    level: str | None
    score: float | None
    percent: float | None
    subject: str | None
    year: int | None
    serial: str | None
    source: Literal["manual", "emis"]
    issued_at: date | None
    expires_at: date | None
    files: list[CertificateFileResponse]
    created_at: datetime

    @classmethod
    def from_domain(cls, entry: CertificateEntry) -> "CertificateEntryResponse":
        """Build the response from the domain entry."""
        return cls(
            id=entry.id,
            type_id=entry.type_id,
            level=entry.level,
            score=entry.score,
            percent=entry.percent,
            subject=entry.subject,
            year=entry.year,
            serial=entry.serial,
            source=entry.source.value,
            issued_at=entry.issued_at,
            expires_at=entry.expires_at,
            files=[CertificateFileResponse.from_domain(f) for f in entry.files],
            created_at=entry.created_at,
        )


class ImportEmisResponse(BaseModel):
    """Result of POST /me/import-emis."""

    created: int
    updated: int
    files: int
    skipped: int

    @classmethod
    def from_result(cls, result: ImportResult) -> "ImportEmisResponse":
        """Build the response from the import result."""
        return cls(
            created=result.created,
            updated=result.updated,
            files=result.files,
            skipped=result.skipped,
        )


class StaffStudent(BaseModel):
    """The student of a staff entry."""

    id: UUID
    name: str
    group_id: UUID
    group_name: str
    subgroup: str | None


class StaffEntryResponse(CertificateEntryResponse):
    """StaffEntry: an entry with its student."""

    student: StaffStudent

    @classmethod
    def from_view(cls, view: StaffEntryView) -> "StaffEntryResponse":
        """Build the response from an entry and its student."""
        base = CertificateEntryResponse.from_domain(view.entry)
        student = view.student
        return cls(
            **base.model_dump(),
            student=StaffStudent(
                id=student.id,
                name=student.name,
                group_id=student.group_id,
                group_name=student.group_name,
                subgroup=student.subgroup,
            ),
        )


class StaffEntriesResponse(BaseModel):
    """A page of staff entries."""

    items: list[StaffEntryResponse]
    total: int

    @classmethod
    def from_page(cls, page: StaffEntriesPage) -> "StaffEntriesResponse":
        """Build the response from a page."""
        return cls(
            items=[StaffEntryResponse.from_view(v) for v in page.items],
            total=page.total,
        )


class GroupCountsResponse(BaseModel):
    """Counts per level of one group."""

    group_id: UUID
    group_name: str
    counts: dict[str, int]


class TypeStatsResponse(BaseModel):
    """Levels of a type and the counts per group."""

    type_id: UUID
    levels: list[str]
    groups: list[GroupCountsResponse]


class StaffStatsResponse(BaseModel):
    """Response of GET /staff/stats."""

    types: list[TypeStatsResponse]

    @classmethod
    def from_stats(cls, stats: list[TypeStats]) -> "StaffStatsResponse":
        """Build the response from the use case result."""
        return cls(
            types=[
                TypeStatsResponse(
                    type_id=item.type_id,
                    levels=item.levels,
                    groups=[
                        GroupCountsResponse(
                            group_id=g.group_id,
                            group_name=g.group_name,
                            counts=g.counts,
                        )
                        for g in item.groups
                    ],
                )
                for item in stats
            ]
        )


class RankingItem(BaseModel):
    """One ranked student."""

    student_id: UUID
    name: str
    group_name: str
    count: int


class StaffRankingResponse(BaseModel):
    """Response of GET /staff/ranking."""

    items: list[RankingItem]

    @classmethod
    def from_ranked(cls, ranked: list[RankedStudent]) -> "StaffRankingResponse":
        """Build the response from the ranked students."""
        return cls(
            items=[
                RankingItem(
                    student_id=r.student_id,
                    name=r.name,
                    group_name=r.group_name,
                    count=r.count,
                )
                for r in ranked
            ]
        )


class StaffGroupResponse(BaseModel):
    """A group for the filter dropdown."""

    id: UUID
    name: str
    subgroups: list[str]

    @classmethod
    def from_info(cls, info: GroupInfo) -> "StaffGroupResponse":
        """Build the response from the group info."""
        return cls(id=info.id, name=info.name, subgroups=list(info.subgroups))


class StaffFiltersBody(BaseModel):
    """Staff filters as a JSON object (export body)."""

    group_id: UUID | None = None
    subgroup: str | None = None
    type_id: UUID | None = None
    subject: str | None = None
    level: str | None = None
    student_id: UUID | None = None
    q: str | None = None

    def to_filters(self) -> StaffFilters:
        """Convert to the use case filters."""
        return StaffFilters(**self.model_dump())


class ExportBody(BaseModel):
    """Body of POST /staff/export: file ids, or filters that pick the files."""

    file_ids: list[UUID] | None = Field(default=None, max_length=1000)
    filters: StaffFiltersBody | None = None
