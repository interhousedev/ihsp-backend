"""Process settings read from environment variables (prefix IHSP_, nested by __)."""

from functools import cache
from pathlib import Path
from typing import Literal

from app.settings_ai import AiSettings, fold_deprecated
from app.settings_features import FeaturesSettings
from app.settings_web_search import WebSearchSettings
from app.shared.ai_tasks import AiTask, ModelProfile
from app.shared.versions import compare_versions, parse_version

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
    """SQLAlchemy URL of the main database; always `postgresql+asyncpg://`."""

    pool_size: int = 10
    """Connections kept open per process."""


class RedisSettings(BaseModel):
    """Redis connection (cache, rate limits, FSM, taskiq broker)."""

    url: str = "redis://localhost:6380/0"
    """Redis URL (cache, rate limits, bot state, task broker)."""


class S3Settings(BaseModel):
    """S3-compatible object storage."""

    endpoint_url: str = "http://localhost:9000"
    """Internal endpoint that does the real object I/O."""

    public_endpoint_url: str = "http://localhost:9000"  # host in presigned URLs
    """Endpoint written into presigned URLs; browsers must reach it."""

    region: str = "us-east-1"
    """S3 region name."""

    access_key: str = "minio"
    """S3 access key id."""

    secret_key: SecretStr = SecretStr(DEV_S3_SECRET)
    """S3 secret key. REQUIRED IN PROD: the development value is refused."""

    bucket: str = "ihsp-dev"
    """Bucket for files and exports."""


class VaultSettings(BaseModel):
    """HashiCorp Vault (EMIS passwords)."""

    url: str = "http://localhost:8200"
    """Vault address (stores the EMIS passwords)."""

    token: SecretStr | None = SecretStr(DEV_VAULT_TOKEN)  # dev only
    """Development root token; in production leave empty and use AppRole."""

    role_id: str | None = None
    """AppRole role id. REQUIRED IN PROD for the identity and worker processes."""

    secret_id: SecretStr | None = None
    """AppRole secret id. REQUIRED IN PROD for the identity and worker processes."""

    verify: bool | str = True
    """TLS verification: `true`, `false` or the path of a CA bundle."""

    transit_key: str = "emis-passwords"
    """Transit key that encrypts the EMIS passwords."""

    kv_mount: str = "secret"
    """KV v2 mount that holds the encrypted passwords."""

    kv_prefix: str = "emis"
    """Path prefix inside the KV mount."""

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
    """Hydra public API (token endpoint, JWKS)."""

    admin_url: str = "http://localhost:4445"
    """Hydra admin API (login and consent handling)."""

    issuer: str = (
        "http://localhost:4444/"  # with the slash, as in Hydra urls.self.issuer
    )
    """Token issuer, with the trailing slash exactly as in Hydra `urls.self.issuer`."""

    jwks_cache_seconds: int = 300
    """How long the verifier caches Hydra's signing keys."""


class JwtBearerSettings(BaseModel):
    """Key that signs identity's own JWT bearer assertions."""

    issuer: str = "ihsp-identity"
    """`iss` claim of the JWT-bearer assertions identity signs."""

    key_id: str = "ihsp-identity-1"
    """`kid` header of those assertions."""

    private_key_path: str | None = None
    """File with the PEM private key. Dev and test generate a key when none is set."""

    # Dev and test generate one in-memory key per process when nothing is set.
    private_key_pem: SecretStr = SecretStr("")
    """The PEM private key itself (wins over the path). REQUIRED IN PROD, with the
    path as the alternative."""

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
    """Lifetime of an access token."""

    refresh_cookie_secure: bool = False  # dev
    """Mark the refresh cookie `Secure`. REQUIRED IN PROD (must be true)."""

    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    """`SameSite` of the refresh cookie. `lax` suits the apps and the API on
    subdomains of one site (prod: *.ihsu.uz). `none` (needs `Secure`) is only for
    local development, where `*.localhost` hosts count as different sites; refused
    in prod."""

    cookie_prefix: str = "rt_"
    """Name prefix of the refresh cookie (followed by the client id)."""

    service_token: SecretStr = SecretStr(DEV_SERVICE_TOKEN)  # worker -> identity
    """Shared token for calls between processes. REQUIRED IN PROD: the development
    value is refused."""


class TelegramSettings(BaseModel):
    """Telegram bot."""

    bot_token: SecretStr = SecretStr(DEV_BOT_TOKEN)
    """Bot token from BotFather."""

    bot_username: str = "ihspbot"
    """Bot username without the @."""

    mode: Literal["polling", "webhook", "fake"] = "fake"
    """`polling`, `webhook` or `fake` (no Telegram at all)."""

    webhook_url: str | None = None
    """Public webhook URL when `MODE=webhook`."""

    webhook_secret: SecretStr | None = None
    """Secret Telegram sends back in the webhook header."""

    admin_chat_id: int | None = None
    """Chat that receives operational alerts; empty disables them."""

    init_data_max_age_seconds: int = 3600
    """How old Mini App `initData` may be."""


class EmisSettings(BaseModel):
    """EMIS client and the identity-process gateway."""

    mode: Literal["real", "fake"] = "fake"
    """`real` talks to EMIS; `fake` uses canned data."""

    base_url: str = "https://emis.edu.uz/api/v1/"
    """EMIS API root."""

    profile_path: str = "student-profiles/profile/"  # README open question 9
    """Path of the student profile endpoint under the base URL."""

    institution_id: int = 10815
    """EMIS id of the institution."""

    concurrency: int = 20
    """Parallel EMIS requests."""

    request_delay_ms: int = 0
    """Pause between EMIS requests (milliseconds)."""

    gateway_url: str = "http://localhost:8000/internal/emis"
    """Where other processes reach the identity-process EMIS gateway."""

    # EMIS topics, topic files, homework files and videos are filled in badly, so the
    # timetable sync leaves them out; times, rooms, teachers, odd/even weeks, halves
    # and the lesson kind (midterm, final) are imported either way.
    import_topics: bool = False


class OpenRouterSettings(BaseModel):
    """LLM gateway (connection only; models and parameters are in `AI__...`)."""

    mode: Literal["real", "fake"] = "fake"
    """`real` calls OpenRouter; `fake` answers from canned rules (no key needed)."""

    api_key: SecretStr | None = None
    """OpenRouter API key; required when `MODE=real`."""

    base_url: str = "https://openrouter.ai/api/v1"
    """OpenRouter API root."""

    model_student: str | None = None
    """Deprecated: use `AI__TASKS__STUDENT_CHAT__MODEL`."""

    model_student_smart: str | None = None
    """Deprecated: use `AI__TASKS__STUDENT_CHAT_SMART__MODEL`."""

    model_admin: str | None = None
    """Deprecated: use `AI__TASKS__ADMIN_CHAT__MODEL`."""

    model_notebook: str | None = None
    """Deprecated: use `AI__TASKS__NOTEBOOK_CHAT__MODEL` and the `STUDIO_*` tasks."""

    model_notebook_light: str | None = None
    """Deprecated: use `AI__TASKS__SOURCE_GUIDE__MODEL`, `..NOTEBOOK_SUMMARY__MODEL`."""

    notebook_data_collection: Literal["deny", "allow"] | None = None
    """Deprecated: use `AI__TASKS__<TASK>__DATA_COLLECTION` (notebook tasks)."""

    app_url: str = "https://sp.ihsu.uz"
    """Sent to OpenRouter as the referring site (HTTP-Referer)."""

    app_title: str = "IHSP"
    """Sent to OpenRouter as the application name (X-Title)."""

    timeout_seconds: int = 90
    """Timeout of assistant calls (notebooks use NOTEBOOKS__LLM_TIMEOUT_SECONDS)."""


class NotebooksSettings(BaseModel):
    """Notebooks (NotebookLM-style) limits and switches.

    See docs/reference/notebooklm.md.
    """

    enabled: bool = True
    """Older master switch of notebooks; both this and FEATURES__NOTEBOOKS must be
    true."""

    llm_timeout_seconds: int = 180
    """Timeout of one notebook model call."""

    max_notebooks: int = 50
    """Notebooks per student."""

    max_sources: int = 50
    """Sources per notebook."""

    source_max_chars: int = 600_000
    """Largest text of one source (characters)."""

    notebook_max_chars: int = 4_000_000
    """Largest total text of one notebook (characters)."""

    add_batch_max: int = 20
    """Sources one add request may carry."""

    max_artifacts: int = 60
    """Studio outputs kept per notebook."""

    chat_full_context_tokens: int = 80_000
    """Up to this many tokens the whole notebook goes to the chat model; above it,
    retrieval picks passages."""

    studio_context_tokens: int = 150_000
    """Token cap of the source pack for Studio outputs."""


class VectorsSettings(BaseModel):
    """Embeddings and search by meaning (docs/reference/vector-search.md).

    The model, vector size and batch size are the `EMBEDDING` AI task (`AI__TASKS__
    EMBEDDING__*`); `FEATURES__VECTOR_SEARCH` switches the whole thing.
    """

    query_timeout_seconds: float = 2.5
    """How long a chat turn waits for the vector of the question; later it searches
    by words only."""

    query_cache_seconds: int = 86_400
    """How long the vector of a question is kept in Redis (same text, same vector)."""

    daily_token_budget: int = 20_000_000
    """Tokens the embedding jobs may spend per day, all together (20 million is about
    USD 0.40 with the default model); the rest waits for tomorrow. 0 means no limit."""

    backfill_texts_per_run: int = 256
    """Distinct passages one `notebooks.embed_passages` run embeds at most (the job
    runs every 10 minutes until every passage has its vector)."""


class LibrarySettings(BaseModel):
    """The library (`library.ihsu.uz`): sizes, quotas, limits and UniLibrary.

    See docs/reference/study-library.md, section 8.2. UniLibrary is a switched-off
    base: it stays off until Administration enables it.
    """

    file_max_bytes: int = 314_572_800
    """Largest file of a book (default 300 MiB)."""

    material_student_max_bytes: int = 20_971_520
    """Largest file of a student's material (default 20 MiB)."""

    material_student_max_pages: int = 60
    """Most pages in a student's material."""

    material_teacher_max_bytes: int = 104_857_600
    """Largest file of a teacher's material (default 100 MiB)."""

    student_quota_bytes: int = 314_572_800
    """Library storage of one student (default 300 MiB), apart from the file quota."""

    teacher_quota_bytes: int = 2_147_483_648
    """Library storage of one teacher (default 2 GiB)."""

    reader_url_seconds: int = 900
    """How long a signed reader URL of a book file lives."""

    teacher_review: bool = False
    """True sends teachers' materials through the librarian queue too; false
    publishes them at once."""

    list_max_items: int = 100
    """Most items in one reading list."""

    limit_uploads_day_student: int = 10
    """Materials a student may upload per day."""

    limit_uploads_week_student: int = 40
    """Materials a student may upload per week."""

    limit_uploads_day_teacher: int = 30
    """Materials a teacher may upload per day."""

    limit_reports_day: int = 10
    """Reports one person may file per day."""

    auto_hold_reporters: int = 2
    """Different reporters that hide an item until a librarian decides."""

    queue_sla_school_days: int = 2
    """School days a librarian has to decide before the queue reminder fires."""

    offline_max_items: int = 5
    """Items one person may keep for offline reading (shown to the app)."""

    offline_max_bytes: int = 419_430_400
    """Bytes of offline items per person (default 400 MiB, shown to the app)."""

    unilibrary_enabled: bool = False
    """UniLibrary (unilibrary.uz) link-only cards. Off until Administration agrees."""

    unilibrary_anonymous_cards: bool = False
    """True shows UniLibrary cards to visitors who are not signed in."""

    unilibrary_base_url: str = "https://api.unilibrary.uz"
    """Base URL of the UniLibrary API."""

    unilibrary_rps: float = 3.0
    """Requests per second sent to UniLibrary, all users together."""

    unilibrary_concurrency: int = 2
    """UniLibrary requests in flight at once."""

    unilibrary_list_timeout: float = 8.0
    """Seconds to wait for a UniLibrary list or search answer."""

    unilibrary_detail_timeout: float = 5.0
    """Seconds to wait for a UniLibrary record."""

    unilibrary_cache_list_ttl: int = 600
    """Seconds a UniLibrary list or search answer is cached."""

    unilibrary_cache_detail_ttl: int = 86_400
    """Seconds a UniLibrary record is cached."""

    unilibrary_stale_ttl: int = 604_800
    """Seconds an expired answer may still be served while UniLibrary is down."""

    unilibrary_breaker_failures: int = 3
    """Failures in a row that open the UniLibrary circuit breaker."""

    unilibrary_breaker_seconds: int = 60
    """Seconds the circuit breaker stays open."""

    unilibrary_user_agent: str = "IHSP-library/1.0 (+https://ihsu.uz)"
    """User-Agent of UniLibrary requests: we say who we are and never pose as a
    browser."""

    unilibrary_contact: str = ""
    """E-mail or URL where UniLibrary can reach us; added to the User-Agent."""

    unilibrary_user_searches_per_min: int = 30
    """UniLibrary searches one person may start per minute."""

    unilibrary_description_max: int = 600
    """Characters of a UniLibrary description kept in a card."""

    public_base_url: str = "https://library.ihsu.uz"
    """Public origin of the library; links in notifications and pages start with it."""

    taxonomy_cache_ttl: int = 604_800
    """Seconds the subject and topic lists are cached."""

    def unilibrary_agent(self) -> str:
        """The User-Agent header: the configured one plus the contact, if any."""
        if not self.unilibrary_contact:
            return self.unilibrary_user_agent
        contact = f"contact: {self.unilibrary_contact}"
        agent = self.unilibrary_user_agent
        if agent.endswith(")"):
            return f"{agent[:-1]}; {contact})"
        return f"{agent} ({contact})"


PUSH_ENDPOINT_SUFFIXES = (
    "googleapis.com",  # FCM: Chrome, Edge-on-Android, Brave, Opera, Samsung Internet
    "push.apple.com",  # APNs web push: Safari and installed iOS apps
    "mozilla.com",  # Firefox (updates.push.services.mozilla.com)
    "notify.windows.com",  # WNS: Edge on Windows
)


class PushSettings(BaseModel):
    """Web Push (VAPID): a second notification channel next to Telegram.

    Generate a key pair with `uv run python scripts/gen_vapid.py`. The private key
    stays in the environment; only the public key is served to browsers.
    """

    enabled: bool = False
    """Turn Web Push on (needs the VAPID keys); also needs FEATURES__PUSH."""

    vapid_public_key: str | None = None  # base64url, uncompressed P-256 point
    vapid_private_key: SecretStr | None = None  # base64url, 32-byte scalar
    subject: str = (
        "mailto:admin@ihsu.uz"  # contact for push services (mailto: or https:)
    )
    per_second: int = Field(default=50, ge=1)
    """Pushes sent per second."""

    timeout_seconds: float = Field(default=10, gt=0)
    """Timeout of one push request."""

    ttl_seconds: int = Field(default=86400, ge=0)
    """How long a push service keeps an undelivered message."""

    # A subscription endpoint is a URL the server calls, so only the known push
    # services are accepted (host equals the suffix or ends with `.suffix`).
    endpoint_suffixes: tuple[str, ...] = PUSH_ENDPOINT_SUFFIXES

    @field_validator("vapid_public_key", "vapid_private_key", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _enabled_needs_keys(self) -> "PushSettings":
        if not self.enabled:
            return self
        if not (self.vapid_public_key and self.vapid_private_key):
            raise ValueError(
                "PUSH__ENABLED needs PUSH__VAPID_PUBLIC_KEY and _PRIVATE_KEY"
            )
        if not self.subject.startswith(("mailto:", "https://")):
            raise ValueError("PUSH__SUBJECT must start with mailto: or https://")
        return self


class SmtpOutSettings(BaseModel):
    """Outbound SMTP relay (Mailpit in dev)."""

    host: str = "localhost"
    """Outbound SMTP relay host."""

    port: int = 1025
    """Outbound SMTP port."""

    username: str | None = None
    """Relay login; empty for none."""

    password: SecretStr | None = None
    """Relay password; empty for none."""

    starttls: bool = False
    """Use STARTTLS with the relay."""

    mail_domain: str = "mail.ihsu.uz"
    """Domain of the students' mailboxes (`<login>@<domain>`)."""

    system_from: str = "no-reply@ihsu.uz"
    """Sender of system emails (activation, reset)."""


class MailOutboundSettings(BaseModel):
    """People-to-people email sent from the platform (compose dialog)."""

    enabled: bool = False
    """Allow students and staff to send email from the platform."""

    host: str = "localhost"
    """SMTP host (Mailpit in development)."""

    port: int = 1025
    """SMTP port."""

    user: str | None = None
    """SMTP login; empty for none."""

    password: SecretStr | None = None
    """SMTP password; empty for none."""

    from_address: str = "no-reply@ihsu.uz"
    """Envelope and header sender; the user's name is shown as the display name."""

    starttls: bool = False
    """Use STARTTLS (port 465 uses implicit TLS)."""

    per_user_per_day: int = 20
    """Emails one user may send per day."""

    max_recipients: int = 5
    """Recipients in one email."""


class MailSettings(BaseModel):
    """Settings of the mail module that are not the mailbox relay."""

    outbound: MailOutboundSettings = Field(default_factory=MailOutboundSettings)


class SmtpInSettings(BaseModel):
    """Inbound SMTP server."""

    host: str = "0.0.0.0"  # the server must listen on all interfaces
    """Address the inbound SMTP server listens on (all interfaces)."""

    port: int = 2525
    """Inbound SMTP port."""

    tls_cert_path: str | None = None
    """TLS certificate for STARTTLS; empty disables it."""

    tls_key_path: str | None = None
    """TLS private key for STARTTLS."""

    max_bytes: int = 26214400
    """Largest accepted message (bytes)."""

    check_spf: bool = False  # dev
    """Run SPF checks on inbound mail (off in dev)."""

    check_dkim: bool = False  # dev
    """Run DKIM checks on inbound mail (off in dev)."""


class UrlsSettings(BaseModel):
    """Public origins of the apps and services."""

    id: str = "http://localhost:3001"
    """Origin of the sign-in app."""

    sp: str = "http://localhost:3002"
    """Origin of the student app."""

    staff: str = "http://localhost:3003"
    """Origin of the teacher app."""

    admin: str = "http://localhost:3004"
    """Origin of the admin app."""

    lms: str = "http://localhost:3005"
    """Origin of the LMS app."""

    share: str = "http://localhost:3006"  # static share app origin
    """Origin of the static share app."""

    app: str = "http://localhost:3007"  # installable PWA, a second `next dev -p 3007`
    """Origin of the installable app (PWA), a second build of the student app."""

    library: str = "http://localhost:3008"
    """Origin of the library app (prod https://library.ihsu.uz)."""

    short_links: str = "http://localhost:8000/s"  # prod https://s.ihsu.uz
    """Base of short links (production: its own host)."""

    rooms: str = "http://localhost:8000/r"  # prod https://ihsu.uz/r
    """Base of room links."""

    api: str = "http://localhost:8000"
    """Origin of the API."""

    mcp: str = "http://localhost:8000/mcp"
    """Base URL of the MCP servers."""


class AppSettings(BaseModel):
    """Release numbers of the installed app, served by GET /v1/app/version.

    Versions are dotted non-negative integers ("1", "1.4", "1.4.2"). The app asks
    for them on start: older than `latest` offers an update, older than
    `min_supported` forces it.
    """

    latest: str = "1.0.0"
    """Newest released version of the installed app."""

    min_supported: str = "1.0.0"
    """Oldest version that may still run; older ones are forced to update."""

    @field_validator("latest", "min_supported")
    @classmethod
    def _dotted_integers(cls, value: str) -> str:
        parse_version(value)
        return value

    @model_validator(mode="after")
    def _min_supported_not_above_latest(self) -> "AppSettings":
        if compare_versions(self.min_supported, self.latest) > 0:
            raise ValueError(
                f"min_supported {self.min_supported} is above latest {self.latest}"
            )
        return self


class LimitsSettings(BaseModel):
    """Quotas and rate limits, per role where the name says so.

    `*_student` and `*_admin` limits belong to that role's users (an admin uses the
    Administration assistant, a student the student one); the rest apply to everyone.
    """

    storage_student_bytes: int = 1610612736
    """File storage quota of a student (default 1.5 GiB)."""

    storage_staff_bytes: int = 10737418240
    """File storage quota of a teacher or admin (default 10 GiB)."""

    file_max_bytes: int = 104857600
    """Largest single upload (default 100 MiB)."""

    ai_text_max_bytes: int = 102400
    """Largest file text the assistant's read_file tool opens (default 100 KiB)."""

    ai_session_hours: int = 5
    """Length of an assistant budget window; a new one starts at the next message."""

    ai_session_tokens_student: int = 200000
    """Student assistant tokens per session window (times the task's budget_weight)."""

    ai_daily_tokens_student: int = 600000
    """Student assistant tokens per day (Tashkent date)."""

    ai_max_tool_steps: int = 8
    """Most model requests (tool rounds) in one assistant turn."""

    ai_smart_weight: int | None = Field(default=None, ge=1)
    """Deprecated: use `AI__TASKS__STUDENT_CHAT_SMART__BUDGET_WEIGHT` (default 4)."""

    mail_per_day: int = 20
    """Messages a student may send per day."""

    mail_recipients: int = 5
    """Recipients allowed in one message."""

    mail_global_per_day: int = 2000
    """Messages the whole system may send per day."""

    otp_codes_per_hour: int = 5
    """One-time codes sent to one account per hour."""

    otp_failures_per_day: int = 10
    """Wrong one-time code attempts allowed per account per day."""

    room_pin_attempts: int = 5
    """Room PIN attempts; reserved, nothing reads it yet."""

    attendance_edit_days: int = 7
    """Days after a lesson during which its attendance can still be edited."""

    nb_session_tokens_student: int = 1_500_000
    """Notebook weighted tokens per session (input + 0.1 x cached + 5 x output)."""

    nb_daily_tokens_student: int = 4_000_000
    """Notebook weighted tokens per day."""

    nb_artifacts_per_day: int = 20
    """Studio outputs a student may start per day."""

    nb_audio_per_day: int = 0
    """Audio overviews per day; 0 switches the counter off (the kind is not built)."""

    nb_slides_per_day: int = 6
    """Slide decks per day (also counts toward nb_artifacts_per_day)."""

    nb_infographics_per_day: int = 6
    """Infographics per day (also counts toward nb_artifacts_per_day)."""

    nb_concurrent_artifacts: int = 3
    """Studio outputs one student may have generating at the same time."""

    nb_chat_per_minute: int = 10
    """Notebook chat messages per minute."""

    nb_source_adds_per_hour: int = 60
    """Sources a student may add per hour."""

    nb_search_per_minute: int = Field(default=30, ge=1)
    """Full-text searches in the sources of notebooks per minute of one user."""

    web_search_per_day_student: int = Field(default=10, ge=0)
    """Web searches a student may start per day (Tashkent date): a chat message with the
    web toggle on counts one, a Discover `fast` search one, a `deep` one
    `web_search_deep_queries`. 0 forbids web search."""

    web_search_per_day_staff: int = Field(default=30, ge=0)
    """Web searches per day of a teacher, administrator or other non-student."""

    web_search_max_results: int = Field(default=5, ge=1, le=10)
    """Results of one search for a chat answer."""

    web_search_discover_results: int = Field(default=8, ge=1, le=20)
    """Results of one search for Discover (`fast` shows them all)."""

    web_search_deep_queries: int = Field(default=3, ge=1, le=5)
    """Searches a Discover `deep` run makes, also what it costs from the daily quota."""

    web_search_deep_results: int = Field(default=12, ge=1, le=25)
    """Results a Discover `deep` run keeps after ranking its searches."""

    lms_ai_session_tokens: int = 1_500_000
    """Course workspace tokens per session window of one staff member (the author
    assistant counts model tokens times the task's budget weight; notebook chat and
    Studio in a workspace count weighted tokens like notebooks do)."""

    lms_ai_daily_tokens: int = 4_000_000
    """Course workspace tokens per day (Tashkent date) of one staff member."""

    lms_ai_artifacts_per_day: int = 30
    """Studio outputs one staff member may start per day in course workspaces."""

    lms_ai_chat_per_minute: int = 12
    """Author assistant and workspace chat messages per minute of one staff member."""

    lms_ai_max_tool_steps: int = 12
    """Most model requests (tool rounds) in one author assistant turn."""


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
    """Environment: `dev`, `test` or `prod`. `prod` refuses the development secrets."""

    log_level: str = "INFO"
    """Log level of every process (DEBUG, INFO, WARNING or ERROR)."""

    public_app_name: str = "IHSP"
    """Product name shown in emails, Telegram messages and the apps."""

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
    notebooks: NotebooksSettings = Field(default_factory=NotebooksSettings)
    vectors: VectorsSettings = Field(default_factory=VectorsSettings)
    library: LibrarySettings = Field(default_factory=LibrarySettings)
    push: PushSettings = Field(default_factory=PushSettings)
    smtp_out: SmtpOutSettings = Field(default_factory=SmtpOutSettings)
    mail: MailSettings = Field(default_factory=MailSettings)
    smtp_in: SmtpInSettings = Field(default_factory=SmtpInSettings)
    urls: UrlsSettings = Field(default_factory=UrlsSettings)
    app: AppSettings = Field(default_factory=AppSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    features: FeaturesSettings = Field(default_factory=FeaturesSettings)
    web_search: WebSearchSettings = Field(default_factory=WebSearchSettings)

    @model_validator(mode="after")
    def _fold_deprecated_variables(self) -> "Settings":
        """Move the old `OPENROUTER__MODEL_*` style variables onto the AI tasks."""
        fold_deprecated(self)
        return self

    def ai_profile(self, task: AiTask) -> ModelProfile:
        """The model, temperature, limits and routing a task runs with."""
        return self.ai.profile(task)

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
        """Origins of the id, sp, staff, admin, lms, app and library apps."""
        urls = self.urls
        return _origins(
            urls.id, urls.sp, urls.staff, urls.admin, urls.lms, urls.app, urls.library
        )

    def cors_share_origins(self) -> list[str]:
        """Origin of the static share app."""
        return _origins(self.urls.share)


def _production_problems(settings: Settings) -> list[str]:
    """Names of shared settings that still hold development defaults."""
    checks = {
        "TOKENS__SERVICE_TOKEN": settings.tokens.service_token.get_secret_value()
        == DEV_SERVICE_TOKEN,
        "TOKENS__REFRESH_COOKIE_SECURE=true": not settings.tokens.refresh_cookie_secure,
        "TOKENS__REFRESH_COOKIE_SAMESITE=lax": settings.tokens.refresh_cookie_samesite
        == "none",
        "S3__SECRET_KEY": settings.s3.secret_key.get_secret_value() == DEV_S3_SECRET,
    }
    return [name for name, is_default in checks.items() if is_default]


def _origins(*values: str) -> list[str]:
    return [value.rstrip("/") for value in values]


def load_settings() -> Settings:
    """Build Settings from the process environment and the files in IHSP_ENV_FILE.

    `IHSP_ENV_FILE` is a comma list of dotenv files (later files win, `?name` is
    optional); invalid values raise `SettingsError` listing every bad variable.
    """
    from app.settings_loader import load_settings as load

    return load()
