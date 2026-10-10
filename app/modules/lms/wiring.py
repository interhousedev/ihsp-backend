"""Assembly of the LMS module: authoring and learning (task I1)."""

from dataclasses import dataclass

from app.modules.lms.wiring_authoring import AuthoringServices, build_authoring
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class LmsModule:
    """`container.lms`: course authoring and student learning."""

    authoring: AuthoringServices
    learning: LearningServices


def build(
    deps: ModuleDeps, *, identity: IdentityDirectory, files: FilesApi
) -> LmsModule:
    """Build authoring first; learning freezes step previews through authoring."""
    authoring = build_authoring(deps, identity=identity, files=files)
    learning = build_learning(
        deps,
        identity=identity,
        preview_revisions=authoring.ensure_preview_revision,
        files=files,
    )
    return LmsModule(authoring=authoring, learning=learning)
