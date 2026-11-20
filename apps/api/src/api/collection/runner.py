import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from api.collection.alerts import WebhookAlert
from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle
from api.collection.source import OlhoVivo, SourceError
from api.collection.store import PostgresStore, RecoveryNotice
from api.config import Settings

logger = logging.getLogger(__name__)


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Settings.model_config.get("env_file"), extra="ignore", hide_input_in_errors=True
    )
    olhovivo_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("CHAVE_API_OLHO_VIVO", "OLHOVIVO_TOKEN", "olhovivo_token"),
    )
    olhovivo_base_url: str = "https://api.olhovivo.sptrans.com.br/v2.1"
    collection_interval_seconds: int = Field(default=30, ge=15, le=60)
    collection_timeout_seconds: float = Field(default=5, gt=0, le=30)
    collection_company_codes: list[int] | None = None
    gtfs_source_id: str = "sptrans"
    collection_max_retries: int = Field(default=5, ge=0, le=5)
    collection_cycle_budget_seconds: float = Field(default=50, gt=0, le=50)
    collection_alert_webhook: SecretStr | None = None
    collection_alert_format: Literal["generic", "discord"] = "generic"
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
    rounds: int = 0
    completed: set[str] = field(default_factory=lambda: set[str]())


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
        self.alert = alert or WebhookAlert(
            settings.collection_alert_webhook, settings.collection_alert_format
        )
        self.guard = guard
        self.last_alert_attempt: float | None = None
        self.storage_down_since: datetime | None = None
        self.storage_alerted_at: datetime | None = None
        self.storage_gap_id: UUID | None = None
        self.storage_incident_id = uuid4()
        self.last_recovery_attempt: float | None = None

    async def attempt(self, cycle_id: UUID, batch: Batch) -> bool:
        queries = tuple(batch.pending)
        if not batch.discovered:
            # Operação independe da descoberta; persistir antes de consultar /Empresa.
            await self.collect_positions(cycle_id, batch, queries)
            try:
                codes = self.settings.collection_company_codes
                if codes is None:
                    codes = await self.source.company_codes()
                if not codes:
                    raise SourceError("no_garages_configured")
            except SourceError as exc:
                batch.errors["companies"] = str(exc)
                return False
            batch.pending.extend(sorted(set(codes)))
            batch.discovered = True
            batch.errors.pop("companies", None)
            # Não repetir a operação duas vezes na mesma tentativa se ela falhou.
            queries = tuple(code for code in batch.pending if code is not None)
        await self.collect_positions(cycle_id, batch, queries)
        return batch.discovered and not batch.pending

    async def collect_positions(
        self, cycle_id: UUID, batch: Batch, queries: tuple[int | None, ...]
    ) -> None:
        for code in queries:
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
            batch.completed.add(key)
            batch.errors.pop(key, None)

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
                    if self.storage_gap_id is None:
                        self.storage_gap_id = await self.store.start(
                            self.storage_down_since, cycle_id=self.storage_incident_id
                        )
                    await self.store.finish(
                        self.storage_gap_id, "storage_failure", "database_unavailable"
                    )
                    if self.storage_alerted_at is not None:
                        await self.store.mark_alerted(self.storage_gap_id, self.storage_alerted_at)
                self.storage_down_since = None
                self.storage_gap_id = None
                self.storage_alerted_at = None
                self.storage_incident_id = uuid4()
            except Exception:
                logger.error("collection_storage_gap_pending")

        batch = Batch()
        status, error = "origin_failure", "attempts_exhausted"
        try:
            async with asyncio.timeout(self.settings.collection_cycle_budget_seconds):
                for attempt in range(self.settings.collection_max_retries + 1):
                    batch.rounds = attempt + 1
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
            for code in batch.pending:
                key = "road" if code is None else f"company_{code}"
                batch.errors.setdefault(key, "cycle_deadline")
        except Exception:
            status, error = "storage_failure", "persistence_failed"

        try:
            async with asyncio.timeout(3):
                details = CycleDiagnostics(
                    status=status,
                    rounds=batch.rounds,
                    road_saved="road" in batch.completed,
                    garages_saved=sum(key.startswith("company_") for key in batch.completed),
                    companies_discovered=batch.discovered,
                    failures=batch.errors.copy(),
                    error=error or None,
                )
                await self.store.record_diagnostics(cycle_id, details)
                await self.store.finish(cycle_id, status, error or None)
        except Exception:
            logger.error("collection_cycle_finish_failed id=%s", cycle_id)
            self.storage_down_since = self.storage_down_since or scheduled_at
            await self.alert_storage_outage()
            return False
        logger.info("collection_cycle_finished id=%s status=%s code=%s", cycle_id, status, error)
        await self.notify_outage()
        return status == "success"

    async def notify_outage(self) -> None:
        no_active_outage = False
        try:
            async with asyncio.timeout(3):
                outage = await self.store.outage()
            no_active_outage = outage is None
            if outage is None or outage.alerted_at is not None:
                return
            if (self.clock.now() - outage.scheduled_at).total_seconds() < 600:
                return
            if not self.alert_attempt_due():
                return
            async with asyncio.timeout(3):
                latest = await self.store.latest_failure(outage.scheduled_at)
            details = None
            if isinstance(latest, CollectionCycle) and latest.diagnostics is not None:
                try:
                    details = CycleDiagnostics.model_validate(latest.diagnostics)
                except ValueError:
                    logger.warning("collection_diagnostics_unavailable")
            if await self.alert.send(
                outage.id, outage.scheduled_at, diagnostics=details, observed_at=self.clock.now()
            ):
                async with asyncio.timeout(3):
                    await self.store.mark_alerted(outage.id, self.clock.now())
        except Exception:
            logger.error("collection_alert_check_failed")
        finally:
            if no_active_outage:
                await self.notify_recovery()

    async def notify_recovery(self) -> None:
        try:
            async with asyncio.timeout(3):
                notice = await self.store.pending_recovery()
            if not isinstance(notice, RecoveryNotice):
                return
            now = self.clock.monotonic()
            if self.last_recovery_attempt is not None and now - self.last_recovery_attempt < 60:
                return
            self.last_recovery_attempt = now
            if await self.alert.send_recovery(
                notice.outage.id, notice.outage.scheduled_at, notice.recovered_at
            ):
                async with asyncio.timeout(3):
                    await self.store.mark_recovery_alerted(notice.outage.id, self.clock.now())
        except Exception:
            logger.error("collection_recovery_delivery_pending")

    def alert_attempt_due(self) -> bool:
        now = self.clock.monotonic()
        if self.last_alert_attempt is not None and now - self.last_alert_attempt < 60:
            return False
        self.last_alert_attempt = now
        return True

    async def alert_storage_outage(self) -> None:
        if self.storage_alerted_at is not None:
            return
        if self.storage_down_since is None:
            return
        if (self.clock.now() - self.storage_down_since).total_seconds() >= 600:
            if self.alert_attempt_due():
                try:
                    sent = await self.alert.send(
                        self.storage_incident_id,
                        self.storage_down_since,
                        diagnostics=CycleDiagnostics(status="storage_failure"),
                        observed_at=self.clock.now(),
                    )
                    if sent:
                        self.storage_alerted_at = self.clock.now()
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
