import asyncio
import logging
from datetime import UTC, datetime

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.collection.source import OlhoVivo, SourceError
from api.collection.store import PostgresStore

logger = logging.getLogger(__name__)


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    olhovivo_token: SecretStr = SecretStr("")
    olhovivo_base_url: str = "https://api.olhovivo.sptrans.com.br/v2.1"
    collection_interval_seconds: int = Field(default=30, ge=15, le=60)
    collection_timeout_seconds: float = Field(default=5, gt=0, le=30)
    collection_company_codes: list[int] | None = None
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    )


class Collector:
    def __init__(self, source: OlhoVivo, store: PostgresStore, settings: CollectionSettings):
        self.source = source
        self.store = store
        self.settings = settings

    async def cycle(self, scheduled_at: datetime) -> bool:
        cycle_id = await self.store.start(scheduled_at)
        failures: list[str] = []
        try:
            await self.store.save(cycle_id, await self.source.snapshot())
            codes = self.settings.collection_company_codes
            if codes is None:
                codes = await self.source.company_codes()
            if not codes:
                raise SourceError("no_garages_configured")
            for code in codes:
                try:
                    await self.store.save(cycle_id, await self.source.snapshot(code))
                except SourceError as exc:
                    failures.append(f"company_{code}:{exc}")
        except SourceError as exc:
            await self.store.finish(cycle_id, "origin_failure", str(exc))
            logger.warning("collection_origin_failure code=%s", str(exc))
            return False
        except Exception:
            await self.store.finish(cycle_id, "storage_failure", "persistence_failed")
            logger.error("collection_storage_failure")
            return False
        if failures:
            await self.store.finish(cycle_id, "origin_failure", ";".join(failures))
            logger.warning("collection_incomplete failed_garages=%s", len(failures))
            return False
        await self.store.finish(cycle_id, "success")
        logger.info("collection_cycle_success id=%s", cycle_id)
        return True

    async def run(self, *, once: bool = False) -> bool:
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            success = await self.cycle(datetime.now(UTC))
            if once:
                return success
            await asyncio.sleep(
                max(0, self.settings.collection_interval_seconds - (loop.time() - started))
            )
