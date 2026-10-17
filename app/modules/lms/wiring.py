"""Assembly of the LMS module: authoring and learning (task I1)."""

import hashlib
import hmac
from dataclasses import dataclass

from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.modules.lms.wiring_authoring import AuthoringServices, build_authoring
from app.modules.lms.wiring_cartridge import CartridgeServices, build_cartridge
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.contracts.academic import GroupDirectory
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class LmsModule:
    """`container.lms`: course authoring and student learning."""

    authoring: AuthoringServices
    learning: LearningServices
    cartridge: CartridgeServices


def h5p_signing_key(deps: ModuleDeps) -> bytes:
    """Derive the H5P URL signing key from the S3 secret (a production secret)."""
    secret = deps.settings.s3.secret_key.get_secret_value().encode()
    return hmac.new(secret, b"ihsp-lms-h5p-links", hashlib.sha256).digest()


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    files: FilesApi,
    h5p_store: H5PObjectStore | None = None,
    groups: GroupDirectory | None = None,
) -> LmsModule:
    """Build authoring first; learning freezes step previews through authoring.

    ``h5p_store`` is the object storage of the files module (S3); without it H5P
    packages are kept in process memory (tests).
    """
    links = H5PLinks(h5p_signing_key(deps), deps.clock, h5p_store)
    authoring = build_authoring(
        deps, identity=identity, files=files, h5p_links=links, groups=groups
    )
    learning = build_learning(
        deps,
        identity=identity,
        preview_revisions=authoring.ensure_preview_revision,
        files=files,
        h5p_links=links,
    )
    cartridge = build_cartridge(deps, identity=identity, files=files)
    return LmsModule(authoring=authoring, learning=learning, cartridge=cartridge)
