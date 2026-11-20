import logging
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, SecretStr

from api.collection.diagnostics import CycleDiagnostics

logger = logging.getLogger(__name__)


class DiscordReceipt(BaseModel):
    id: str = Field(min_length=1)


class DiscordRateLimit(BaseModel):
    retry_after: float = Field(ge=0, allow_inf_nan=False)


def local_time(when: datetime) -> str:
    return when.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")


def duration(start: datetime, end: datetime) -> str:
    seconds = max(0, int((end - start).total_seconds()))
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min {seconds} s"


def field(name: str, value: str, *, inline: bool = False) -> dict[str, object]:
    return {"name": name, "value": value[:1000], "inline": inline}


class WebhookAlert:
    def __init__(
        self, url: SecretStr | None, webhook_format: Literal["generic", "discord"] = "generic"
    ):
        self.url = url
        self.webhook_format = webhook_format
        self.retry_at = 0.0

    async def send(
        self,
        cycle_id: UUID,
        started_at: datetime,
        *,
        test: bool = False,
        diagnostics: CycleDiagnostics | None = None,
        observed_at: datetime | None = None,
        simulation: bool = False,
    ) -> bool:
        now = observed_at or datetime.now(UTC)
        if test or simulation:
            logger.info("collection_alert_test")
        else:
            logger.error("collection_outage since=%s cycle=%s", started_at.isoformat(), cycle_id)
        message = (
            "TESTE — integração de alertas. Não indica uma falha real."
            if test
            else "A coleta está incompleta há pelo menos dez minutos."
        )
        payload: dict[str, object] = {
            "event": "collection_alert_test" if test else "collection_outage",
            "cycle_id": str(cycle_id),
            "started_at": started_at.isoformat(),
            "text": message,
        }
        if simulation:
            message = "**SIMULAÇÃO — não indica uma falha real.**\n\n" + message
            payload.update(text=message, simulation=True)
        if diagnostics is not None:
            payload["diagnostics"] = diagnostics.model_dump(mode="json")
        if self.webhook_format == "discord":
            fields = [
                field(
                    "Horário do teste" if test else "Início da ocorrência",
                    local_time(started_at),
                    inline=True,
                )
            ]
            if not test:
                fields.append(field("Duração observada", duration(started_at, now), inline=True))
                sections = (
                    diagnostics.sections()
                    if diagnostics
                    else {"Diagnóstico": "Detalhes indisponíveis. Consulte os logs do coletor."}
                )
                fields.extend(field(name, value) for name, value in sections.items())
            payload = {
                "allowed_mentions": {"parse": []},
                "embeds": [
                    {
                        "title": (
                            "🧪 Teste de alertas"
                            if test
                            else "🧪 Simulação · coleta incompleta"
                            if simulation
                            else "⚠️ Coleta incompleta"
                        ),
                        "description": message,
                        "color": 0xFEE75C if test else 0xED4245,
                        "fields": fields,
                        "timestamp": now.isoformat(),
                        "footer": {
                            "text": f"Ônibus SP · ocorrência {cycle_id} · horários de São Paulo"
                        },
                    }
                ],
            }
        return await self.deliver(payload)

    async def send_recovery(
        self,
        cycle_id: UUID,
        started_at: datetime,
        recovered_at: datetime,
        *,
        simulation: bool = False,
    ) -> bool:
        message = (
            "Um ciclo completo voltou a ser gravado. "
            "As lacunas anteriores permanecem registradas; nenhum dado foi inventado."
        )
        if simulation:
            message = "**SIMULAÇÃO — não confirma uma recuperação real.**\n\n" + message
        payload: dict[str, object] = {
            "event": "collection_recovered",
            "cycle_id": str(cycle_id),
            "started_at": started_at.isoformat(),
            "recovered_at": recovered_at.isoformat(),
            "text": message,
        }
        if simulation:
            payload["simulation"] = True
        if self.webhook_format == "discord":
            payload = {
                "allowed_mentions": {"parse": []},
                "embeds": [
                    {
                        "title": (
                            "🧪 Simulação · coleta restabelecida"
                            if simulation
                            else "✅ Coleta restabelecida"
                        ),
                        "description": message,
                        "color": 0x57F287,
                        "fields": [
                            field("Início da ocorrência", local_time(started_at), inline=True),
                            field("Recuperação confirmada", local_time(recovered_at), inline=True),
                            field("Duração da ocorrência", duration(started_at, recovered_at)),
                        ],
                        "timestamp": recovered_at.isoformat(),
                        "footer": {
                            "text": f"Ônibus SP · ocorrência {cycle_id} · horários de São Paulo"
                        },
                    }
                ],
            }
        logger.info("collection_recovery simulation=%s cycle=%s", simulation, cycle_id)
        return await self.deliver(payload)

    async def deliver(self, payload: dict[str, object]) -> bool:
        if self.url is None or not self.url.get_secret_value():
            logger.warning("collection_alert_destination_not_configured")
            return False
        if time.monotonic() < self.retry_at:
            return False
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                url = httpx.URL(self.url.get_secret_value())
                if self.webhook_format == "discord":
                    url = url.copy_merge_params({"wait": "true"})
                response = await client.post(url, json=payload)
                if self.webhook_format == "discord" and response.status_code == 429:
                    try:
                        delay = DiscordRateLimit.model_validate_json(response.content).retry_after
                    except ValueError:
                        delay = 60.0
                    self.retry_at = time.monotonic() + max(1.0, delay)
                    logger.warning("collection_discord_rate_limited")
                    return False
                response.raise_for_status()
                if self.webhook_format == "discord":
                    if response.status_code != 200:
                        return False
                    DiscordReceipt.model_validate_json(response.content)
            return True
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            logger.error("collection_webhook_delivery_failed")
            return False
