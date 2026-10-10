"""ORM models of the notebooks module (schema ``notebooks``)."""

from app.modules.notebooks.infrastructure.orm.artifact import Artifact
from app.modules.notebooks.infrastructure.orm.artifact_asset import ArtifactAsset
from app.modules.notebooks.infrastructure.orm.artifact_progress import (
    ArtifactProgress,
)
from app.modules.notebooks.infrastructure.orm.default_material import (
    SubjectDefaultMaterial,
)
from app.modules.notebooks.infrastructure.orm.document import (
    Document,
    DocumentAlias,
    DocumentGuide,
)
from app.modules.notebooks.infrastructure.orm.label import (
    SourceLabel,
    SourceLabelLink,
    SourceLabelRun,
)
from app.modules.notebooks.infrastructure.orm.message import Message
from app.modules.notebooks.infrastructure.orm.notebook import Notebook
from app.modules.notebooks.infrastructure.orm.passage import Passage
from app.modules.notebooks.infrastructure.orm.shared_cache import (
    SharedArtifact,
    SharedSummary,
)
from app.modules.notebooks.infrastructure.orm.source import Source

__all__ = [
    "Artifact",
    "ArtifactAsset",
    "ArtifactProgress",
    "Document",
    "DocumentAlias",
    "DocumentGuide",
    "Message",
    "Notebook",
    "Passage",
    "SharedArtifact",
    "SharedSummary",
    "Source",
    "SubjectDefaultMaterial",
    "SourceLabel",
    "SourceLabelLink",
    "SourceLabelRun",
]
