import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.gtfs.catalog import Catalog
from api.gtfs.source import GtfsError, download, inspect_feed
from api.gtfs.storage import Archive

logger = logging.getLogger(__name__)


class GtfsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    gtfs_source_url: SecretStr = SecretStr("")
    gtfs_source_id: str = Field(default="sptrans", pattern=r"^[a-z0-9_-]{1,64}$")
    gtfs_interval_seconds: int = Field(default=86400, ge=60, le=604800)
    gtfs_failure_interval_seconds: int = Field(default=300, ge=1, le=3600)
    gtfs_timeout_seconds: float = Field(default=60, gt=0, le=120)
    gtfs_attempts: int = Field(default=3, ge=1, le=5)
    gtfs_max_bytes: int = Field(default=268_435_456, gt=0)
    gtfs_max_expanded_bytes: int = Field(default=4_294_967_296, gt=0)
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    )
    s3_endpoint_url: str | None = "http://localhost:4566"
    s3_access_key: SecretStr = SecretStr("test")
    s3_secret_key: SecretStr = SecretStr("test")
    s3_bucket: str = "raw-data"
    s3_region: str = "us-east-1"


class GtfsCollector:
    def __init__(
        self,
        client: httpx.AsyncClient,
        archive: Archive,
        catalog: Catalog,
        settings: GtfsSettings,
    ):
        self.client = client
        self.archive = archive
        self.catalog = catalog
        self.settings = settings

    async def cycle(self) -> bool:
        try:
            with TemporaryDirectory(prefix="amarelo-gtfs-") as directory:
                path = Path(directory) / "feed.zip"
                await download(
                    self.client,
                    self.settings.gtfs_source_url.get_secret_value(),
                    path,
                    max_bytes=self.settings.gtfs_max_bytes,
                    attempts=self.settings.gtfs_attempts,
                )
                metadata = await asyncio.to_thread(
                    inspect_feed,
                    path,
                    max_expanded_bytes=self.settings.gtfs_max_expanded_bytes,
                )
                key = await asyncio.to_thread(
                    self.archive.preserve,
                    path,
                    self.settings.gtfs_source_id,
                    metadata,
                )
                # Só publicar uma captura depois de o objeto estar preservado.
                await self.catalog.record(
                    metadata,
                    source_id=self.settings.gtfs_source_id,
                    source_url=self.settings.gtfs_source_url.get_secret_value(),
                    captured_at=datetime.now(UTC),
                    bucket=self.settings.s3_bucket,
                    key=key,
                )
            logger.info("gtfs_capture_success sha256=%s", metadata.sha256)
            return True
        except GtfsError as exc:
            logger.warning("gtfs_cycle_failed code=%s", str(exc))
        except Exception:
            # Bibliotecas podem incluir credenciais/URLs/SQL nos erros; não propagá-los.
            logger.error("gtfs_cycle_failed code=storage_or_configuration_failure")
        return False

    async def run(self, *, once: bool = False) -> bool:
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            success = await self.cycle()
            if once:
                return success
            interval = self.settings.gtfs_interval_seconds
            if not success:
                interval = min(interval, self.settings.gtfs_failure_interval_seconds)
            await asyncio.sleep(max(0, interval - (loop.time() - started)))
