from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    olho_vivo_token: SecretStr = SecretStr("")
    olho_vivo_base_url: str = "https://api.olhovivo.sptrans.com.br/v2.1"

    network_catalog_path: str | None = None

    app_name: str = "Sprint Amarelo API"
    database_url: str = "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "raw-data"
    s3_region: str = "us-east-1"
    cors_origins: list[str] = Field(default=["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
