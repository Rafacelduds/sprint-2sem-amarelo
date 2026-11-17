from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sprint Amarelo API"
    database_url: str = "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    s3_endpoint_url: str = "http://localhost:4566"
    s3_access_key: str = "test"
    s3_secret_key: str = "test"
    s3_bucket: str = "raw-data"
    s3_region: str = "us-east-1"
    cors_origins: list[str] = Field(default=["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
