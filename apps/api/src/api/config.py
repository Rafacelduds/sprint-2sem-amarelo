from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

OLHO_VIVO_TOKEN_ALIASES = AliasChoices(
    "CHAVE_API_OLHO_VIVO", "OLHOVIVO_TOKEN", "OLHO_VIVO_TOKEN", "olhovivo_token", "olho_vivo_token"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env", extra="ignore", env_ignore_empty=True
    )

    olho_vivo_token: SecretStr = Field(
        default=SecretStr(""), validation_alias=OLHO_VIVO_TOKEN_ALIASES
    )
    olho_vivo_base_url: str = "https://api.olhovivo.sptrans.com.br/v2.1"

    network_catalog_path: str | None = None
    schedule_source_url: str = "https://itinerariosapi.sptrans.com.br"
    gtfs_source_id: str = "sptrans"
    network_cache_dir: Path = Path(__file__).resolve().parents[4] / "data" / "network"

    app_name: str = "Sprint Amarelo API"
    operations_token: SecretStr = SecretStr("")
    database_url: str = "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "raw-data"
    s3_region: str = "us-east-1"
    s3_restore_map: Path | None = None
    cors_origins: list[str] = Field(default=["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
