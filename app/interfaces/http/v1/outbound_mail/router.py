"""Routes of email sent from the platform (`/v1/me/outbound-mail`)."""

from app.interfaces.http.v1.outbound_mail.handlers import send

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me/outbound-mail", tags=["mail"])

router.add_api_route("", send.send_outbound_mail, methods=["POST"])
