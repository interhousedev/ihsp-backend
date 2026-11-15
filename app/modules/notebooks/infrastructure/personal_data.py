"""Personal-data specification of the notebooks module (export and erasure)."""

from app.modules.notebooks.infrastructure.orm.artifact import Artifact
from app.modules.notebooks.infrastructure.orm.artifact_progress import ArtifactProgress
from app.modules.notebooks.infrastructure.orm.default_material import (
    SubjectDefaultMaterial,
)
from app.modules.notebooks.infrastructure.orm.message import Message
from app.modules.notebooks.infrastructure.orm.notebook import Notebook
from app.modules.notebooks.infrastructure.orm.presentation_plan import PresentationPlan
from app.modules.notebooks.infrastructure.orm.share import NotebookShareRow
from app.modules.notebooks.infrastructure.orm.source import Source
from app.shared.personal_data import (
    ParentLink,
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N, R = Treatment.ERASE, Treatment.NULLIFY, Treatment.RETAIN
_ = ParentLink

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(
        ArtifactProgress, E, owner="user_id", note="erased by notebooks.delete_owner"
    ),
    PersonalTable(
        NotebookShareRow, E, owner="user_id", note="erased by notebooks.delete_owner"
    ),
    PersonalTable(
        SubjectDefaultMaterial,
        E,
        owner="teacher_id",
        note="erased by notebooks.delete_owner",
    ),
    PersonalTable(
        Message, E, owner="owner_id", note="erased by notebooks.delete_owner"
    ),
    PersonalTable(
        PresentationPlan, E, owner="owner_id", note="erased by notebooks.delete_owner"
    ),
    PersonalTable(
        Artifact, E, owner="owner_id", note="erased by notebooks.delete_owner"
    ),
    PersonalTable(Source, E, owner="owner_id", note="erased by notebooks.delete_owner"),
    PersonalTable(
        Notebook, E, owner="owner_id", note="erased by notebooks.delete_owner"
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
