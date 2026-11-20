"""Assembly of the LMS module: authoring and learning (task I1)."""

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from app.modules.ai.domain.requests import AiRequestSpec
from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.learning.audience import StudentGroupLookup
from app.modules.lms.application.public_course_ops import LmsCourseOpsImpl
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.modules.lms.wiring_authoring import AuthoringServices, build_authoring
from app.modules.lms.wiring_cartridge import CartridgeServices, build_cartridge
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.contracts.academic import GroupDirectory, ScheduleQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps

# AI requests this module declares; the AI module publishes them at startup.
AI_REQUESTS: tuple[AiRequestSpec, ...] = ()


@dataclass(slots=True)
class LmsModule:
    """`container.lms`: course authoring and student learning."""

    authoring: AuthoringServices
    learning: LearningServices
    cartridge: CartridgeServices
    course_ops: LmsCourseOpsImpl


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
    students: ScheduleQueries | None = None,
) -> LmsModule:
    """Build authoring first; learning freezes step previews through authoring.

    ``h5p_store`` is the object storage of the files module (S3); without it H5P
    packages are kept in process memory (tests). ``students`` resolves the group
    of a student for the audience rules; without it group rules match nobody.
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
        student_group=_student_group(students) if students is not None else None,
    )
    cartridge = build_cartridge(deps, identity=identity, files=files)
    course_ops = LmsCourseOpsImpl(
        apply_outline_ops=authoring.apply_outline_ops,
        apply_course_plan=authoring.apply_course_plan,
        get_step_draft=authoring.get_step_draft,
        save_step_draft=authoring.save_step_draft,
        get_pending_changes=authoring.get_pending_changes,
        publish_course=authoring.publish_course,
        restore_version=authoring.restore_version,
        get_course_settings=authoring.get_course_settings,
        update_course_settings=authoring.update_course_settings,
        list_course_staff=authoring.list_course_staff,
        add_course_staff=authoring.add_course_staff,
        remove_course_staff=authoring.remove_course_staff,
        list_course_students=learning.list_course_students,
        get_attempt=learning.get_attempt,
        override_score=learning.override_score,
        set_access_rule=authoring.set_access_rule,
    )
    return LmsModule(
        authoring=authoring,
        learning=learning,
        cartridge=cartridge,
        course_ops=course_ops,
    )


def _student_group(students: ScheduleQueries) -> StudentGroupLookup:
    """Return a lookup of the group of an active student."""

    async def lookup(user_id: UUID) -> UUID | None:
        student = await students.get_student(user_id)
        if student is None or student.status != "active":
            return None
        return student.group_id

    return lookup
