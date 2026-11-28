"""Personal-data specification of the identity module (export and erasure)."""

from app.modules.identity.infrastructure.orm.audit_event import AuditEvent
from app.modules.identity.infrastructure.orm.card_qr_token import StudentCardQrTokenRow
from app.modules.identity.infrastructure.orm.factors import PasskeyRow, UserFactorsRow
from app.modules.identity.infrastructure.orm.login_cue import LoginCueRow
from app.modules.identity.infrastructure.orm.mcp_call_log import McpCallLogRow
from app.modules.identity.infrastructure.orm.mcp_connector import McpConnector
from app.modules.identity.infrastructure.orm.mcp_scope_offer import McpScopeOffer
from app.modules.identity.infrastructure.orm.personal_token import PersonalTokenRow
from app.modules.identity.infrastructure.orm.session import Session
from app.modules.identity.infrastructure.orm.telegram_link import TelegramLink
from app.modules.identity.infrastructure.orm.user import User
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
    PersonalTable(Session, E, owner="user_id"),
    PersonalTable(
        StudentCardQrTokenRow,
        E,
        owner="user_id",
        note="metadata only",
        exclude=("token",),
    ),
    PersonalTable(
        PersonalTokenRow, E, owner="user_id", note="metadata only", exclude=("hash",)
    ),
    PersonalTable(
        McpConnector, E, owner="user_id", note="metadata only", exclude=("token_hash",)
    ),
    PersonalTable(McpCallLogRow, E, owner="user_id"),
    PersonalTable(McpScopeOffer, E, owner="user_id"),
    PersonalTable(
        PasskeyRow,
        E,
        owner="user_id",
        note="names only",
        exclude=("credential_id", "public_key"),
    ),
    PersonalTable(
        UserFactorsRow,
        E,
        owner="user_id",
        note="flags only",
        exclude=("totp_secret_enc", "recovery_code_hashes"),
    ),
    PersonalTable(TelegramLink, E, owner="user_id"),
    PersonalTable(
        LoginCueRow,
        N,
        owner="consumed_by_user_id",
        note="registration cue, EMIS login encrypted",
    ),
    PersonalTable(AuditEvent, R, owner="user_id", note="audit trail"),
    PersonalTable(
        User,
        Treatment.ANONYMISE,
        owner="id",
        note="anonymised by purge_deleted_users",
        exclude=(
            "password_hash",
            "activation_token_hash",
            "emis_vault_ref",
            "otp_reset_request_id",
        ),
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
