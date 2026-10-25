"""Build the Hydra adapters from settings."""

from app.modules.identity.infrastructure.hydra.admin import HydraAdmin
from app.settings import Settings

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MiniappClientSettings(BaseSettings):
    """The confidential Hydra client used for the Telegram mini app grant.

    Not part of the shared Settings (B0), so identity reads its own two
    variables: IHSP_HYDRA__MINIAPP_CLIENT_ID and IHSP_HYDRA__MINIAPP_CLIENT_SECRET.
    """

    model_config = SettingsConfigDict(
        env_prefix="IHSP_HYDRA__", extra="ignore", case_sensitive=False
    )

    miniapp_client_id: str = "miniapp"
    miniapp_client_secret: SecretStr = SecretStr("dev-miniapp-secret")


def build_hydra_admin(settings: Settings) -> HydraAdmin:
    """Create the Hydra client for the identity process."""
    miniapp = MiniappClientSettings()
    return HydraAdmin(
        admin_url=settings.hydra.admin_url,
        public_url=settings.hydra.public_url,
        miniapp_client_id=miniapp.miniapp_client_id,
        miniapp_client_secret=miniapp.miniapp_client_secret.get_secret_value(),
    )
