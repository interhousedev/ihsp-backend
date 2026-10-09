"""Builds the materials area of the library."""

from dataclasses import dataclass

from app.modules.library.application.materials.attach_material_files import (
    AttachMaterialFiles,
)
from app.modules.library.application.materials.create_material import CreateMaterial
from app.modules.library.application.materials.create_material_version import (
    CreateMaterialVersion,
)
from app.modules.library.application.materials.create_suggestion import (
    CreateSuggestion,
)
from app.modules.library.application.materials.decide_suggestion import (
    DecideSuggestion,
)
from app.modules.library.application.materials.decisions import Decisions
from app.modules.library.application.materials.delete_owner import (
    DeleteOwnerMaterials,
)
from app.modules.library.application.materials.drafts import MaterialDrafts
from app.modules.library.application.materials.list_my_uploads import ListMyUploads
from app.modules.library.application.materials.list_queue import ListQueue
from app.modules.library.application.materials.purge_files import PurgeFiles
from app.modules.library.application.materials.remind_queue import RemindQueue
from app.modules.library.application.materials.report_item import ReportItem
from app.modules.library.application.materials.resolve_report import ResolveReport
from app.modules.library.application.materials.review_item import ReviewItem
from app.modules.library.application.materials.review_rights import ReviewRights
from app.modules.library.application.materials.sanctions import (
    CreateSanction,
    ListSanctions,
)
from app.modules.library.application.materials.submit_material import SubmitMaterial
from app.modules.library.application.materials.update_material import UpdateMaterial
from app.modules.library.application.materials.upload_guard import UploadGuard
from app.modules.library.application.materials.withdraw_material import (
    WithdrawMaterial,
)
from app.modules.library.domain.moderation_rules import UploadLimits
from app.modules.library.wiring_core import LibraryCore


@dataclass(frozen=True, slots=True)
class MaterialsServices:
    """Use cases of the materials area."""

    create_material: CreateMaterial
    attach_material_files: AttachMaterialFiles
    submit_material: SubmitMaterial
    update_material: UpdateMaterial
    create_material_version: CreateMaterialVersion
    withdraw_material: WithdrawMaterial
    list_my_uploads: ListMyUploads
    review_item: ReviewItem
    report_item: ReportItem
    resolve_report: ResolveReport
    list_queue: ListQueue
    create_suggestion: CreateSuggestion
    decide_suggestion: DecideSuggestion
    create_sanction: CreateSanction
    list_sanctions: ListSanctions
    remind_queue: RemindQueue
    review_rights: ReviewRights
    purge_files: PurgeFiles
    delete_owner: DeleteOwnerMaterials


def build_materials(core: LibraryCore) -> MaterialsServices:
    """Wire the use cases of the materials area."""
    settings = core.settings
    guard = UploadGuard(
        clock=core.clock,
        limits=UploadLimits(
            student_day=settings.limit_uploads_day_student,
            student_week=settings.limit_uploads_week_student,
            teacher_day=settings.limit_uploads_day_teacher,
        ),
    )
    drafts = MaterialDrafts(
        clock=core.clock,
        files=core.files,
        identity=core.identity,
        academic=core.academic,
        kicker=core.kicker,
        guard=guard,
        settings=settings,
    )
    decisions = Decisions(clock=core.clock)
    return MaterialsServices(
        create_material=CreateMaterial(
            uow_factory=core.uow_factory, drafts=drafts, detail=core.detail
        ),
        attach_material_files=AttachMaterialFiles(
            uow_factory=core.uow_factory,
            clock=core.clock,
            files=core.files,
            drafts=drafts,
            detail=core.detail,
            settings=settings,
        ),
        submit_material=SubmitMaterial(
            uow_factory=core.uow_factory,
            clock=core.clock,
            guard=guard,
            detail=core.detail,
            teacher_review=settings.teacher_review,
        ),
        update_material=UpdateMaterial(
            uow_factory=core.uow_factory,
            clock=core.clock,
            drafts=drafts,
            detail=core.detail,
        ),
        create_material_version=CreateMaterialVersion(
            uow_factory=core.uow_factory, drafts=drafts, detail=core.detail
        ),
        withdraw_material=WithdrawMaterial(
            uow_factory=core.uow_factory, clock=core.clock, drafts=drafts
        ),
        list_my_uploads=ListMyUploads(uow_factory=core.uow_factory, cards=core.cards),
        review_item=ReviewItem(
            uow_factory=core.uow_factory, decisions=decisions, detail=core.detail
        ),
        report_item=ReportItem(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            decisions=decisions,
            settings=settings,
        ),
        resolve_report=ResolveReport(
            uow_factory=core.uow_factory, clock=core.clock, decisions=decisions
        ),
        list_queue=ListQueue(
            uow_factory=core.uow_factory,
            clock=core.clock,
            cards=core.cards,
            identity=core.identity,
            academic=core.academic,
        ),
        create_suggestion=CreateSuggestion(
            uow_factory=core.uow_factory, clock=core.clock, files=core.files
        ),
        decide_suggestion=DecideSuggestion(uow_factory=core.uow_factory),
        create_sanction=CreateSanction(
            uow_factory=core.uow_factory, clock=core.clock, identity=core.identity
        ),
        list_sanctions=ListSanctions(uow_factory=core.uow_factory),
        remind_queue=RemindQueue(
            uow_factory=core.uow_factory,
            clock=core.clock,
            identity=core.identity,
            settings=settings,
        ),
        review_rights=ReviewRights(
            uow_factory=core.uow_factory, clock=core.clock, identity=core.identity
        ),
        purge_files=PurgeFiles(
            uow_factory=core.uow_factory, clock=core.clock, files=core.files
        ),
        delete_owner=DeleteOwnerMaterials(
            uow_factory=core.uow_factory, clock=core.clock, files=core.files
        ),
    )
