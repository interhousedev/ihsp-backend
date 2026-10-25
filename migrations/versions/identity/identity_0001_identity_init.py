"""identity init

Revision ID: identity_0001
Revises:
Create Date: 2026-10-07 16:59:30.218610

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "identity_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("identity",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create schema id with users, sessions, Telegram links, connectors, audit."""
    op.execute("CREATE SCHEMA IF NOT EXISTS id")
    op.create_table(
        "audit_events",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        schema="id",
    )
    op.create_index(
        "ix_audit_events_created_at",
        "audit_events",
        ["created_at"],
        unique=False,
        schema="id",
    )
    op.create_index(
        "ix_audit_events_type_created_at",
        "audit_events",
        ["type", "created_at"],
        unique=False,
        schema="id",
    )
    op.create_index(
        "ix_audit_events_user_id_created_at",
        "audit_events",
        ["user_id", "created_at"],
        unique=False,
        schema="id",
    )
    op.create_table(
        "users",
        sa.Column("login", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("middle_name", sa.String(length=255), nullable=True),
        sa.Column(
            "roles", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("recovery_email", sa.String(length=320), nullable=True),
        sa.Column(
            "recovery_email_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "otp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "otp_via_email",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "unregistered",
                "pending_activation",
                "active",
                "blocked",
                "deactivated",
                "deleted",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "auth_epoch", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("activation_token_hash", sa.String(length=64), nullable=True),
        sa.Column("activation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "activation_purpose",
            sa.Enum(
                "activate",
                "reset_password",
                name="activation_purpose",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("emis_student_id", sa.Integer(), nullable=True),
        sa.Column("emis_vault_ref", sa.Uuid(), nullable=True),
        sa.Column(
            "emis_status",
            sa.Enum(
                "active",
                "needs_reauth",
                name="emis_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("mail_suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_reset_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_reset_request_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint(
            "activation_token_hash", name="uq_users_activation_token_hash"
        ),
        sa.UniqueConstraint("emis_student_id", name="uq_users_emis_student_id"),
        sa.UniqueConstraint("emis_vault_ref", name="uq_users_emis_vault_ref"),
        sa.UniqueConstraint("login", name="uq_users_login"),
        schema="id",
    )
    op.create_index(
        "ix_users_recovery_email_lower",
        "users",
        [sa.literal_column("lower(recovery_email)")],
        unique=True,
        schema="id",
    )
    op.create_index(
        "ix_users_roles",
        "users",
        ["roles"],
        unique=False,
        schema="id",
        postgresql_using="gin",
    )
    op.create_table(
        "mcp_connectors",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "server",
            sa.Enum(
                "student",
                "lms",
                "admin",
                name="server",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "scopes",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("course_ids", sa.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_prefix", sa.String(length=16), nullable=True),
        sa.Column("hydra_client_id", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["id.users.id"],
            name=op.f("fk_mcp_connectors_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_connectors")),
        sa.UniqueConstraint("token_hash", name="uq_mcp_connectors_token_hash"),
        schema="id",
    )
    op.create_index(
        "ix_mcp_connectors_hydra_client_id",
        "mcp_connectors",
        ["hydra_client_id"],
        unique=False,
        schema="id",
    )
    op.create_index(
        "ix_mcp_connectors_user_id",
        "mcp_connectors",
        ["user_id"],
        unique=False,
        schema="id",
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hydra_sid", sa.String(length=255), nullable=True),
        sa.Column(
            "amr", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("mfa_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["id.users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("hydra_sid", name="uq_sessions_hydra_sid"),
        schema="id",
    )
    op.create_index(
        "ix_sessions_user_id", "sessions", ["user_id"], unique=False, schema="id"
    )
    op.create_table(
        "telegram_links",
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "otp_delivery", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["id.users.id"],
            name=op.f("fk_telegram_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_links")),
        sa.UniqueConstraint(
            "telegram_user_id", name="uq_telegram_links_telegram_user_id"
        ),
        schema="id",
    )
    op.create_index(
        "ix_telegram_links_user_id",
        "telegram_links",
        ["user_id"],
        unique=False,
        schema="id",
    )


def downgrade() -> None:
    """Drop the id tables and the schema."""
    op.drop_index("ix_telegram_links_user_id", table_name="telegram_links", schema="id")
    op.drop_table("telegram_links", schema="id")
    op.drop_index("ix_sessions_user_id", table_name="sessions", schema="id")
    op.drop_table("sessions", schema="id")
    op.drop_index("ix_mcp_connectors_user_id", table_name="mcp_connectors", schema="id")
    op.drop_index(
        "ix_mcp_connectors_hydra_client_id", table_name="mcp_connectors", schema="id"
    )
    op.drop_table("mcp_connectors", schema="id")
    op.drop_index(
        "ix_users_roles", table_name="users", schema="id", postgresql_using="gin"
    )
    op.drop_index("ix_users_recovery_email_lower", table_name="users", schema="id")
    op.drop_table("users", schema="id")
    op.drop_index(
        "ix_audit_events_user_id_created_at", table_name="audit_events", schema="id"
    )
    op.drop_index(
        "ix_audit_events_type_created_at", table_name="audit_events", schema="id"
    )
    op.drop_index("ix_audit_events_created_at", table_name="audit_events", schema="id")
    op.drop_table("audit_events", schema="id")
    op.execute("DROP SCHEMA IF EXISTS id CASCADE")
