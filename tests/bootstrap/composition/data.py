"""Builders of the domain objects that the provider modules return."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.results import (
    GroupItemData,
    PersonData,
    StudentProfileData,
    TermData,
)
from app.modules.academic.domain.lesson_item import lesson_item
from app.modules.admin.application.broadcast_view import BroadcastView
from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import (
    Broadcast,
    BroadcastStats,
    BroadcastStatus,
    CreatedVia,
)
from app.modules.files.application.file_views import FileView
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.shared.actor import Role
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id
from tests.composition.fakes import make_lesson

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
TODAY = dt.date(2026, 10, 6)
TERM_START = dt.date(2026, 9, 2)
TERM_END = dt.date(2026, 12, 30)


def lesson_json(
    ref: LessonRef | None = None,
    *,
    teacher: dict[str, Any] | None = None,
    **lesson_fields: Any,
) -> dict[str, Any]:
    """A `LessonItem` dict as the schedule module builds it."""
    ref = ref or make_lesson(**lesson_fields)
    return lesson_item(
        ref,
        teacher=teacher,
        subject_short=None,
        audience=[
            {"group_id": str(new_id()), "group_name": "2TN2", "subgroup": None},
        ],
        attendance_submitted=False,
        has_homework=False,
        is_overridden=False,
        changes=None,
    )


def person_json(
    first_name: str = "Nodira", last_name: str = "Aliyeva"
) -> dict[str, Any]:
    """A `PersonRef` dict."""
    return {"id": str(new_id()), "first_name": first_name, "last_name": last_name}


def make_view(
    name: str = "notes.pdf",
    *,
    owner_id: UUID | None = None,
    status: FileStatus = FileStatus.READY,
    expires_on: dt.date | None = None,
    file_id: UUID | None = None,
) -> FileView:
    """A file as `ListMyFiles` returns it."""
    file = StoredFile(
        id=file_id or new_id(),
        owner_id=owner_id or new_id(),
        scope=FileScope.STUDENT,
        purpose=FilePurpose.AI_UPLOAD,
        key=f"files/{name}",
        name=name,
        content_type="application/pdf",
        byte_size=1234,
        checksum="x",
        status=status,
        created_at=NOW,
        updated_at=NOW,
        text_bytes=500,
    )
    return FileView(file=file, expires_on=expires_on, used_by=[], assistant_ready=True)


def make_term_data(
    starts_on: dt.date = TERM_START, ends_on: dt.date = TERM_END
) -> TermData:
    """A current term."""
    return TermData(
        id=new_id(),
        academic_year="2026-2027",
        half=1,
        starts_on=starts_on,
        ends_on=ends_on,
        bells=[],
        non_study_days=[],
        moved_days=[],
        is_current=True,
    )


def make_profile_data(user_id: UUID) -> StudentProfileData:
    """The flat read model of `GetStudentProfile`."""
    return StudentProfileData(
        user_id=user_id,
        login="karimova.aziza",
        first_name="Aziza",
        last_name="Karimova",
        mailbox="karimova.aziza@mail.ihsu.uz",
        group_id=new_id(),
        group_name="2TN2",
        subgroup=1,
        curator=PersonData(id=new_id(), first_name="Nodira", last_name="Aliyeva"),
        head_student=None,
        current_semester=3,
        emis_status="active",
        synced_at=NOW,
    )


def make_group_data(name: str = "2TN2") -> GroupItemData:
    """A `GroupItemData` row."""
    return GroupItemData(
        id=new_id(),
        name=name,
        slug=name.lower(),
        current_semester=3,
        status="active",
        students_count=25,
        subgroups_assigned=20,
        unregistered_count=2,
        curator=PersonData(id=new_id(), first_name="Nodira", last_name="Aliyeva"),
        head_student=None,
    )


def make_user_ref(*roles: Role) -> UserRef:
    """A user as the identity directory returns it."""
    return UserRef(
        id=new_id(),
        login="karimova.aziza",
        first_name="Aziza",
        last_name="Karimova",
        middle_name=None,
        roles=frozenset(roles),
        status=UserStatus.ACTIVE,
        locale="en",
        emis_status="active",
    )


def make_broadcast_view(
    title: str,
    *,
    scheduled_at: dt.datetime | None,
    status: BroadcastStatus = BroadcastStatus.SCHEDULED,
) -> BroadcastView:
    """A broadcast with its author, as `ListBroadcasts` returns it."""
    author = make_user_ref(Role.ADMIN)
    broadcast = Broadcast(
        id=new_id(),
        author_id=author.id,
        created_via=CreatedVia.UI,
        title=title,
        text="Text",
        audience=Audience(everyone=True),
        created_at=NOW,
        scheduled_at=scheduled_at,
        status=status,
        stats=BroadcastStats(total=0, sent=0, failed=0, blocked=0),
    )
    return BroadcastView(broadcast=broadcast, author=author, stats=broadcast.stats)
