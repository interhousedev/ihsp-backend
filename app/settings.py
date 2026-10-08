"""Process settings read from environment variables (prefix IHSP_, nested by __)."""

import os
from functools import cache
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SERVICE_TOKEN = "dev-service-token"
DEV_VAULT_TOKEN = "dev-root"
DEV_S3_SECRET = "minio12345"
DEV_BOT_TOKEN = "000:dev"

# Processes that hold EMIS secrets (Vault AppRole) and the JWT-bearer signing key. The
# others (api, bot, mail, scheduler, migrate) never see either in production.
SECRET_HOLDING_PROCESSES = frozenset(
    {"identity", "worker", "all", "create-user", "seed-demo"}
)


@cache
def _ephemeral_private_key() -> str:
    """Generate one RSA key per process for dev and test (never used in prod)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pem.decode()


class DatabaseSettings(BaseModel):
    """PostgreSQL connection."""

    url: str = "postgresql+asyncpg://ihsp:ihsp@localhost:5433/ihsp"
    pool_size: int = 10


class RedisSettings(BaseModel):
    """Redis connection (cache, rate limits, FSM, taskiq broker)."""

    url: str = "redis://localhost:6380/0"


class S3Settings(BaseModel):
    """S3-compatible object storage."""

    endpoint_url: str = "http://localhost:9000"
    public_endpoint_url: str = "http://localhost:9000"  # host in presigned URLs
    region: str = "us-east-1"
    access_key: str = "minio"
    secret_key: SecretStr = SecretStr(DEV_S3_SECRET)
    bucket: str = "ihsp-dev"


class VaultSettings(BaseModel):
    """HashiCorp Vault (EMIS passwords)."""

    url: str = "http://localhost:8200"
    token: SecretStr | None = SecretStr(DEV_VAULT_TOKEN)  # dev only
    role_id: str | None = None
    secret_id: SecretStr | None = None
    verify: bool | str = True
    transit_key: str = "emis-passwords"
    kv_mount: str = "secret"
    kv_prefix: str = "emis"

    @field_validator("verify", mode="before")
    @classmethod
    def _bool_from_env(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value

    @field_validator("token", "secret_id", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value


class HydraSettings(BaseModel):
    """Ory Hydra endpoints."""

    public_url: str = "http://localhost:4444"
    admin_url: str = "http://localhost:4445"
    issuer: str = (
        "http://localhost:4444/"  # with the slash, as in Hydra urls.self.issuer
    )
    jwks_cache_seconds: int = 300


class JwtBearerSettings(BaseModel):
    """Key that signs identity's own JWT bearer assertions."""

    issuer: str = "ihsp-identity"
    key_id: str = "ihsp-identity-1"
    private_key_path: str | None = None
    # Dev and test generate one in-memory key per process when nothing is set.
    private_key_pem: SecretStr = SecretStr("")
    _ephemeral: bool = PrivateAttr(default=False)

    @property
    def ephemeral(self) -> bool:
        """True when the key was generated in memory (never acceptable in prod)."""
        return self._ephemeral

    @model_validator(mode="after")
    def _load_key(self) -> "JwtBearerSettings":
        if self.private_key_pem.get_secret_value():
            return self
        if self.private_key_path:
            try:
                pem = Path(self.private_key_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(
                    f"cannot read JWT_BEARER__PRIVATE_KEY_PATH: {exc}"
                ) from exc
            self.private_key_pem = SecretStr(pem)
        else:
            self.private_key_pem = SecretStr(_ephemeral_private_key())
            self._ephemeral = True
        return self


class TokensSettings(BaseModel):
    """Access and refresh token handling."""

    access_ttl_seconds: int = 600
    refresh_cookie_secure: bool = False  # dev
    cookie_prefix: str = "rt_"
    service_token: SecretStr = SecretStr(DEV_SERVICE_TOKEN)  # worker -> identity


class TelegramSettings(BaseModel):
    """Telegram bot."""

    bot_token: SecretStr = SecretStr(DEV_BOT_TOKEN)
    bot_username: str = "ihspbot"
    mode: Literal["polling", "webhook", "fake"] = "fake"
    webhook_url: str | None = None
    webhook_secret: SecretStr | None = None
    admin_chat_id: int | None = None
    init_data_max_age_seconds: int = 3600


class EmisSettings(BaseModel):
    """EMIS client and the identity-process gateway."""

    mode: Literal["real", "fake"] = "fake"
    base_url: str = "https://emis.edu.uz/api/v1/"
    profile_path: str = "student-profiles/profile/"  # README open question 9
    institution_id: int = 10815
    concurrency: int = 20
    request_delay_ms: int = 0
    gateway_url: str = "http://localhost:8000/internal/emis"


class OpenRouterSettings(BaseModel):
    """LLM gateway."""

    mode: Literal["real", "fake"] = "fake"
    api_key: SecretStr | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    model_student: str = "anthropic/claude-haiku-4.5"
    model_admin: str = "anthropic/claude-haiku-4.5"
    app_url: str = "https://sp.ihsu.uz"
    app_title: str = "IHSP"
    timeout_seconds: int = 90


class SmtpOutSettings(BaseModel):
    """Outbound SMTP relay (Mailpit in dev)."""

    host: str = "localhost"
    port: int = 1025
    username: str | None = None
    password: SecretStr | None = None
    starttls: bool = False
    mail_domain: str = "mail.ihsu.uz"
    system_from: str = "no-reply@ihsu.uz"


class SmtpInSettings(BaseModel):
    """Inbound SMTP server."""

    host: str = "0.0.0.0"  # the server must listen on all interfaces
    port: int = 2525
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    max_bytes: int = 26214400
    check_spf: bool = False  # dev
    check_dkim: bool = False  # dev


class UrlsSettings(BaseModel):
    """Public origins of the apps and services."""

    id: str = "http://localhost:3001"
    sp: str = "http://localhost:3002"
    staff: str = "http://localhost:3003"
    admin: str = "http://localhost:3004"
    lms: str = "http://localhost:3005"
    share: str = "http://localhost:3006"  # static share app origin
    short_links: str = "http://localhost:8000/s"  # prod https://s.ihsu.uz
    rooms: str = "http://localhost:8000/r"  # prod https://ihsu.uz/r
    api: str = "http://localhost:8000"
    mcp: str = "http://localhost:8000/mcp"


class LimitsSettings(BaseModel):
    """Quotas and rate limits."""

    storage_student_bytes: int = 1610612736
    storage_staff_bytes: int = 10737418240
    file_max_bytes: int = 104857600
    ai_text_max_bytes: int = 102400
    ai_session_hours: int = 5
    ai_session_tokens_student: int = 200000
    ai_daily_tokens_student: int = 600000
    ai_session_tokens_admin: int = 400000
    ai_daily_tokens_admin: int = 1200000
    ai_max_tool_steps: int = 8
    mail_per_day: int = 20
    mail_recipients: int = 5
    mail_global_per_day: int = 2000
    otp_codes_per_hour: int = 5
    otp_failures_per_day: int = 10
    room_pin_attempts: int = 5
    attendance_edit_days: int = 7


class Settings(BaseSettings):
    """All settings of one process; development defaults match materials/dev.env."""

    model_config = SettingsConfigDict(
        env_prefix="IHSP_",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,  # `IHSP_X=` in a file means "not set"
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    public_app_name: str = "IHSP"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    hydra: HydraSettings = Field(default_factory=HydraSettings)
    jwt_bearer: JwtBearerSettings = Field(default_factory=JwtBearerSettings)
    tokens: TokensSettings = Field(default_factory=TokensSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    emis: EmisSettings = Field(default_factory=EmisSettings)
    openrouter: OpenRouterSettings = Field(default_factory=OpenRouterSettings)
    smtp_out: SmtpOutSettings = Field(default_factory=SmtpOutSettings)
    smtp_in: SmtpInSettings = Field(default_factory=SmtpInSettings)
    urls: UrlsSettings = Field(default_factory=UrlsSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)

    @model_validator(mode="after")
    def _production_guard(self) -> "Settings":
        """Refuse development defaults that every process would share in production."""
        if self.env != "prod":
            return self
        if self.vault.role_id and self.vault.secret_id:
            self.vault.token = None  # AppRole replaces the dev token
        elif (
            self.vault.token is not None
            and self.vault.token.get_secret_value() == DEV_VAULT_TOKEN
        ):
            self.vault.token = None  # the dev token is never used in production
        problems = _production_problems(self)
        if problems:
            raise ValueError("production settings missing: " + ", ".join(problems))
        return self

    def require_production_ready(self, process: str) -> None:
        """Check what only some processes need: Vault AppRole and the JWT key.

        Called once at process start (`python -m app <process>`). Only the identity and
        worker processes (and the commands that run in their environment) read EMIS
        secrets or sign assertions, so the others start without those secrets.
        """
        if self.env != "prod" or process not in SECRET_HOLDING_PROCESSES:
            return
        problems = []
        if not (self.vault.role_id and self.vault.secret_id):
            problems.append("VAULT__ROLE_ID and VAULT__SECRET_ID")
        if self.jwt_bearer.ephemeral:
            problems.append("JWT_BEARER__PRIVATE_KEY_PEM or _PATH")
        if problems:
            raise ValueError(
                f"production settings missing for {process}: " + ", ".join(problems)
            )

    def cors_app_origins(self) -> list[str]:
        """Origins of the id, sp, staff, admin and lms apps."""
        urls = self.urls
        return _origins(urls.id, urls.sp, urls.staff, urls.admin, urls.lms)

    def cors_share_origins(self) -> list[str]:
        """Origin of the static share app."""
        return _origins(self.urls.share)


def _production_problems(settings: Settings) -> list[str]:
    """Names of shared settings that still hold development defaults."""
    checks = {
        "TOKENS__SERVICE_TOKEN": settings.tokens.service_token.get_secret_value()
        == DEV_SERVICE_TOKEN,
        "TOKENS__REFRESH_COOKIE_SECURE=true": not settings.tokens.refresh_cookie_secure,
        "S3__SECRET_KEY": settings.s3.secret_key.get_secret_value() == DEV_S3_SECRET,
    }
    return [name for name, is_default in checks.items() if is_default]


def _origins(*values: str) -> list[str]:
    return [value.rstrip("/") for value in values]


def load_settings() -> Settings:
    """Build Settings, reading the file named by IHSP_ENV_FILE if it is set."""
    env_file = os.environ.get("IHSP_ENV_FILE") or None
    return Settings(_env_file=env_file)
