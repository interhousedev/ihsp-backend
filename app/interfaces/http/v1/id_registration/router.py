"""Routes of registration, reclaim, EMIS password update and account deletion."""

from app.interfaces.http.v1.id_registration.handlers.delete_account import (
    delete_account,
)
from app.interfaces.http.v1.id_registration.handlers.reclaim_complete import (
    reclaim_complete,
)
from app.interfaces.http.v1.id_registration.handlers.reclaim_email import reclaim_email
from app.interfaces.http.v1.id_registration.handlers.reclaim_emis import reclaim_emis
from app.interfaces.http.v1.id_registration.handlers.register_complete import (
    register_complete,
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
    DeleteAccountResponse,
    EmisPasswordResponse,
    RegistrationStartResponse,
    StartReclaimResponse,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/id", tags=["id-registration"])

router.add_api_route(
    "/register/emis",
    register_emis,
    methods=["POST"],
    response_model=RegistrationStartResponse,
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
