from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class CollectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    s3_endpoint_url: str = "http://localhost:4566"
    s3_access_key: str = "test"
    s3_secret_key: str = "test"
    s3_bucket: str = "raw-data"
    s3_region: str = "us-east-1"
    collector_poll_seconds: int = 30


@lru_cache
def get_settings() -> CollectorSettings:
    return CollectorSettings()
