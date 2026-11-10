"""SqlExcuseFileUsage against Postgres: the uuid[] overlap query (GET /v1/me/files)."""

import datetime as dt

from app.modules.academic.infrastructure.excuses.file_usage import SqlExcuseFileUsage
from app.modules.academic.infrastructure.orm.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseTemplate,
)
from app.shared.ids import new_id

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_used_by_files_finds_attachments_of_thread_messages(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    group_id, student_id = new_id(), new_id()
    attached, other, unused = new_id(), new_id(), new_id()
    template = ExcuseTemplate(
        id=new_id(), code="illness-t", title={"en": "x"}, requires_document=False
    )
    excuse = Excuse(
        id=new_id(),
        student_id=student_id,
        origin="request",
        status="pending",
        template_id=template.id,
        starts_on=dt.date(2026, 10, 6),
        created_by=student_id,
    )
    async with sessionmaker_in_tx() as session:
        await session.execute(
            text(
                "INSERT INTO academic.groups (id, name, slug, status) "
                "VALUES (:id, 'T1', 't1-files', 'active')"
            ),
            {"id": group_id},
        )
        await session.execute(
            text(
                "INSERT INTO academic.students (user_id, group_id, status) "
                "VALUES (:sid, :gid, 'active')"
            ),
            {"sid": student_id, "gid": group_id},
        )
        session.add(template)
        await session.flush()
        session.add(excuse)
        await session.flush()
        session.add_all(
            [
                ExcuseMessage(
                    id=new_id(),
                    excuse_id=excuse.id,
                    author_id=student_id,
                    file_ids=[attached, other],
                ),
                ExcuseMessage(
                    id=new_id(),
                    excuse_id=excuse.id,
                    author_id=student_id,
                    file_ids=[attached],
                ),
            ]
        )
        await session.commit()

    used = await SqlExcuseFileUsage(sessionmaker_in_tx).used_by_files(
        [attached, unused]
    )

    assert used == {attached: [("excuse", excuse.id, "illness-t")]}
