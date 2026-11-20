import logging
import time
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, SecretStr

logger = logging.getLogger(__name__)


class DiscordReceipt(BaseModel):
    id: str = Field(min_length=1)


class DiscordRateLimit(BaseModel):
    retry_after: float = Field(ge=0, allow_inf_nan=False)


class WebhookAlert:
    def __init__(
        self, url: SecretStr | None, webhook_format: Literal["generic", "discord"] = "generic"
    ):
        self.url = url
        self.webhook_format = webhook_format
        self.retry_at = 0.0

    async def send(self, cycle_id: UUID, started_at: datetime, *, test: bool = False) -> bool:
        # O log é o fallback local; só marcar entregue após resposta HTTP de sucesso.
        if test:
            logger.info("collection_alert_test")
        else:
            logger.error("collection_outage since=%s cycle=%s", started_at.isoformat(), cycle_id)
        if self.url is None or not self.url.get_secret_value():
            logger.warning("collection_alert_destination_not_configured")
            return False
        if time.monotonic() < self.retry_at:
            return False
        message = (
            "TESTE — integração de alertas da coleta. Não indica uma falha real."
            if test
            else "Coleta Olho Vivo incompleta há pelo menos dez minutos."
        )
        event = "collection_alert_test" if test else "collection_outage"
        payload: dict[str, object] = {
            "event": event,
            "cycle_id": str(cycle_id),
            "started_at": started_at.isoformat(),
            "text": message,
        }
        if self.webhook_format == "discord":
            local_time = started_at.astimezone(ZoneInfo("America/Sao_Paulo"))
            label = "Horário do teste" if test else "Início da falha"
            payload = {
                "content": (
                    f"**Alertas da coleta — ônibus SP**\n{message}\n"
                    f"{label}: {local_time:%d/%m/%Y %H:%M:%S} (São Paulo)\n"
                    f"Ocorrência: `{cycle_id}`"
                ),
                "allowed_mentions": {"parse": []},
            }
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
