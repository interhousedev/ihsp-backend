"""`python -m app backfill-profile-photos`: profile photos from enrolled faces.

Copies the face of every user who has one but no profile photo. Never replaces a
photo the user or an administrator chose. Idempotent: run it again any time. Prints
counts only.
"""

import argparse
import asyncio
import sys

from app.bootstrap.adapters.faces import FacesProfilePhotoAdapter
from app.bootstrap.common import build_container
from app.modules.faces.application.backfill_profile_photos import (
    BackfillProfilePhotos,
    BackfillResult,
    EnrolledFace,
)
from app.modules.faces.infrastructure.orm.tables import FaceProfileRow
from app.settings import Settings
from app.shared.logging import configure_logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlEnrolledFaces:
    """Reads every enrolled face straight from the faces table."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self._sessionmaker = sessionmaker

    async def all(self) -> list[EnrolledFace]:
        """Return every enrolled face, oldest first."""
        statement = select(
            FaceProfileRow.user_id, FaceProfileRow.photo_file_id
        ).order_by(FaceProfileRow.created_at)
        async with self._sessionmaker() as session:
            rows = (await session.execute(statement)).all()
        return [EnrolledFace(user_id=row[0], photo_file_id=row[1]) for row in rows]


async def _backfill(settings: Settings) -> BackfillResult:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="cli")
    try:
        files = container.files.public
        use_case = BackfillProfilePhotos(
            faces=SqlEnrolledFaces(container.sessionmaker),
            files=files,
            profile_photos=FacesProfilePhotoAdapter(
                container.identity.directory,
                files,
                container.identity.auth.set_user_photo,
                container.identity.auth.remove_user_photo,
            ),
        )
        return await use_case.execute()
    finally:
        await container.close()
        await broker.shutdown()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the backfill and print the counts; exit 1 when any user failed."""
    configure_logging(settings.log_level, json_logs=False)
    result = asyncio.run(_backfill(settings))
    sys.stdout.write(
        f"Profile photos: set {result.set}, skipped {result.skipped}, "
        f"failed {result.failed}\n"
    )
    return 1 if result.failed else 0
