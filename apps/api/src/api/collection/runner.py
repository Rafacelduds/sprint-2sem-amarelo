import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from api.collection.alerts import WebhookAlert
from api.collection.source import OlhoVivo, SourceError
from api.collection.store import PostgresStore

logger = logging.getLogger(__name__)


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    olhovivo_token: SecretStr = SecretStr("")
    olhovivo_base_url: str = "https://api.olhovivo.sptrans.com.br/v2.1"
    collection_interval_seconds: int = Field(default=30, ge=15, le=60)
    collection_timeout_seconds: float = Field(default=5, gt=0, le=30)
    collection_company_codes: list[int] | None = None
    collection_max_retries: int = Field(default=5, ge=0, le=5)
    collection_cycle_budget_seconds: float = Field(default=50, gt=0, le=50)
    collection_alert_webhook: SecretStr | None = None
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://amarelo:amarelo@localhost:5432/amarelo"
    )

    @field_validator("olhovivo_base_url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Olho Vivo exige HTTPS")
        return value.rstrip("/")

    @field_validator("collection_alert_webhook")
    @classmethod
    def validate_webhook(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        if not value.get_secret_value().startswith("https://"):
            raise ValueError("webhook exige HTTPS")
        return value


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass
class Batch:
    pending: list[int | None] = field(default_factory=lambda: [None])
    discovered: bool = False
    errors: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    saving: bool = False


class Collector:
    def __init__(
        self,
        source: OlhoVivo,
        store: PostgresStore,
        settings: CollectionSettings,
        *,
        clock: Clock | None = None,
        alert: WebhookAlert | None = None,
        guard: AsyncConnection | None = None,
    ):
        self.source = source
        self.store = store
        self.settings = settings
        self.clock = clock or Clock()
        self.alert = alert or WebhookAlert(settings.collection_alert_webhook)
        self.guard = guard
        self.last_alert_attempt: float | None = None
        self.storage_down_since: datetime | None = None

    async def attempt(self, cycle_id: UUID, batch: Batch) -> bool:
        if not batch.discovered:
            codes = self.settings.collection_company_codes
            if codes is None:
                codes = await self.source.company_codes()
            if not codes:
                raise SourceError("no_garages_configured")
            batch.pending.extend(sorted(set(codes)))
            batch.discovered = True
        for code in tuple(batch.pending):
            batch.saving = False
            key = "road" if code is None else f"company_{code}"
            try:
                snapshot = await self.source.snapshot(code)
            except SourceError as exc:
                batch.errors[key] = str(exc)
                continue
            batch.saving = True
            await self.store.save(cycle_id, snapshot)
            batch.saving = False
            batch.pending.remove(code)
            batch.errors.pop(key, None)
        return not batch.pending

    async def cycle(self, scheduled_at: datetime) -> bool:
        try:
            async with asyncio.timeout(3):
                cycle_id = await self.store.start(scheduled_at)
        except Exception:
            self.storage_down_since = self.storage_down_since or scheduled_at
            logger.error("collection_cycle_start_failed")
            await self.alert_storage_outage()
            return False

        # Se o banco esteve inacessível, registrar o intervalo ao voltar, sem inventar GPS.
        if self.storage_down_since is not None:
            try:
                async with asyncio.timeout(3):
                    gap_id = await self.store.start(self.storage_down_since)
                    await self.store.finish(gap_id, "storage_failure", "database_unavailable")
                self.storage_down_since = None
            except Exception:
                logger.error("collection_storage_gap_pending")

        batch = Batch()
        status, error = "origin_failure", "attempts_exhausted"
        try:
            async with asyncio.timeout(self.settings.collection_cycle_budget_seconds):
                for attempt in range(self.settings.collection_max_retries + 1):
                    try:
                        if await self.attempt(cycle_id, batch):
                            status, error = "success", ""
                            break
                        error = ";".join(f"{k}:{v}" for k, v in batch.errors.items())
                    except SourceError as exc:
                        error = str(exc)
                    if attempt < self.settings.collection_max_retries:
                        delay = 2**attempt
                        logger.warning("collection_retry attempt=%s delay=%s", attempt + 1, delay)
                        await self.clock.sleep(delay)
        except TimeoutError:
            if batch.saving:
                status = "storage_failure"
            error = "cycle_deadline"
        except Exception:
            status, error = "storage_failure", "persistence_failed"

        try:
            async with asyncio.timeout(3):
                await self.store.finish(cycle_id, status, error or None)
        except Exception:
            logger.error("collection_cycle_finish_failed id=%s", cycle_id)
            self.storage_down_since = self.storage_down_since or scheduled_at
            return False
        logger.info("collection_cycle_finished id=%s status=%s code=%s", cycle_id, status, error)
        await self.notify_outage()
        return status == "success"

    async def notify_outage(self) -> None:
        try:
            async with asyncio.timeout(3):
                outage = await self.store.outage()
            if outage is None or outage.alerted_at is not None:
                return
            if (self.clock.now() - outage.scheduled_at).total_seconds() < 600:
                return
            if not self.alert_attempt_due():
                return
            if await self.alert.send(outage.id, outage.scheduled_at):
                async with asyncio.timeout(3):
                    await self.store.mark_alerted(outage.id, self.clock.now())
        except Exception:
            logger.error("collection_alert_check_failed")

    def alert_attempt_due(self) -> bool:
        now = self.clock.monotonic()
        if self.last_alert_attempt is not None and now - self.last_alert_attempt < 60:
            return False
        self.last_alert_attempt = now
        return True

    async def alert_storage_outage(self) -> None:
        if self.storage_down_since is None:
            return
        if (self.clock.now() - self.storage_down_since).total_seconds() >= 600:
            if self.alert_attempt_due():
                try:
                    await self.alert.send(UUID(int=0), self.storage_down_since)
                except Exception:
                    logger.error("collection_storage_alert_failed")

    async def run(self, *, once: bool = False) -> bool:
        while True:
            if self.guard is not None:
                # Se a conexão que mantém o lock cair, reiniciar e disputar o lock novamente.
                async with asyncio.timeout(3):
                    await self.guard.execute(text("SELECT 1"))
            started = self.clock.monotonic()
            success = await self.cycle(self.clock.now())
            if once:
                return success
            await self.clock.sleep(
                max(
                    0,
                    self.settings.collection_interval_seconds - (self.clock.monotonic() - started),
                )
            )
