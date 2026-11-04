"""The brand names users see: one settings-backed source for every process.

Locale files and AI prompts hold the placeholders of `with_brand`; bot messages, mail,
notifications, prompts and display names all read the same value. A rebrand sets
`IHSP_PUBLIC_APP_NAME` and `IHSP_BRAND__*`.

Prompts are module constants, so the value is needed at import, before `Settings`
exists; this module reads only its own variables, from the same sources.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

from app.settings_loader import ENV_FILE_VARIABLE, parse_env_files

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_APP_NAME = "IHT"


class BrandSettings(BaseModel):
    """Names of the school and the platform; the short name is PUBLIC_APP_NAME."""

    org_name: str = "International House Tashkent"
    """Full name of the school."""

    org_alias: str = "Interhouse"
    """Familiar name of the school."""

    library_site: str = "library.iht"
    """Name of the library site in its page metadata."""


class _BrandEnv(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IHSP_",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    public_app_name: str = DEFAULT_APP_NAME
    brand: BrandSettings = BrandSettings()


@dataclass(frozen=True, slots=True)
class Brand:
    """The resolved names."""

    name: str
    org_name: str
    org_alias: str
    library_site: str

    @property
    def id_name(self) -> str:
        """Name of the account service ("<name> ID")."""
        return f"{self.name} ID"


@lru_cache(maxsize=1)
def current_brand() -> Brand:
    """The brand of this process, read once."""
    files = parse_env_files(os.environ.get(ENV_FILE_VARIABLE))
    env = _BrandEnv(_env_file=tuple(files) or None)
    return Brand(
        name=env.public_app_name,
        org_name=env.brand.org_name,
        org_alias=env.brand.org_alias,
        library_site=env.brand.library_site,
    )


def with_brand(text: str) -> str:
    """Fill `{brand}`, `{brand_id}`, `{org_name}`, `{org_alias}`, `{library_site}`.

    Other placeholders stay for a later `str.format`.
    """
    brand = current_brand()
    for token, value in (
        ("{brand}", brand.name),
        ("{brand_id}", brand.id_name),
        ("{org_name}", brand.org_name),
        ("{org_alias}", brand.org_alias),
        ("{library_site}", brand.library_site),
    ):
        text = text.replace(token, value)
    return text
