"""Routes of registration, reclaim, EMIS password update and account deletion."""

from app.interfaces.http.feature_gate import require_feature
from app.interfaces.http.v1.id_registration.handlers.change_emis_password import (
    change_emis_password,
)
from app.interfaces.http.v1.id_registration.handlers.delete_account import (
    delete_account,
)
from app.interfaces.http.v1.id_registration.handlers.login_cues import (
    list_cue_groups,
    list_group_cues,
    start_cue_registration,
)
from app.interfaces.http.v1.id_registration.handlers.reclaim_complete import (
    reclaim_complete,
)
from app.interfaces.http.v1.id_registration.handlers.reclaim_email import reclaim_email
from app.interfaces.http.v1.id_registration.handlers.reclaim_emis import reclaim_emis
from app.interfaces.http.v1.id_registration.handlers.register_complete import (
    register_complete,
    register_telegram_status,
)
from app.interfaces.http.v1.id_registration.handlers.register_email import (
    register_email,
)
from app.interfaces.http.v1.id_registration.handlers.register_emis import register_emis
from app.interfaces.http.v1.id_registration.handlers.update_emis_password import (
    update_emis_password,
)
from app.interfaces.http.v1.id_registration.schemas import (
    CompleteRegistrationResponse,
    CueGroupResponse,
    CueOptionResponse,
    DeleteAccountResponse,
    EmisPasswordResponse,
    RegistrationStartResponse,
    StartReclaimResponse,
    TelegramLinkStatusResponse,
)
from app.shared.features import Feature

from fastapi import APIRouter, Depends, Response, status

router = APIRouter(prefix="/v1/id", tags=["id-registration"])

_CUES_ON = [Depends(require_feature(Feature.LOGIN_CUES))]

router.add_api_route(
    "/register/emis",
    register_emis,
    methods=["POST"],
    response_model=RegistrationStartResponse,
)
router.add_api_route(
    "/login-cues/groups",
    list_cue_groups,
    methods=["GET"],
    response_model=list[CueGroupResponse],
    dependencies=_CUES_ON,
)
router.add_api_route(
    "/login-cues/groups/{group_id}",
    list_group_cues,
    methods=["GET"],
    response_model=list[CueOptionResponse],
    dependencies=_CUES_ON,
)
router.add_api_route(
    "/register/emis/cue",
    start_cue_registration,
    methods=["POST"],
    response_model=RegistrationStartResponse,
    dependencies=_CUES_ON,
)
router.add_api_route(
    "/register/email",
    register_email,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/register/complete",
    register_complete,
    methods=["POST"],
    response_model=CompleteRegistrationResponse,
)
router.add_api_route(
    "/reclaim/emis",
    reclaim_emis,
    methods=["POST"],
    response_model=StartReclaimResponse,
)
router.add_api_route(
    "/reclaim/email",
    reclaim_email,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/reclaim/complete",
    reclaim_complete,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/register/telegram-status",
    register_telegram_status,
    methods=["POST"],
    response_model=TelegramLinkStatusResponse,
)
router.add_api_route(
    "/me/emis-password/change",
    change_emis_password,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/me/emis-password",
    update_emis_password,
    methods=["POST"],
    response_model=EmisPasswordResponse,
)
router.add_api_route(
    "/me",
    delete_account,
    methods=["DELETE"],
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DeleteAccountResponse,
)
