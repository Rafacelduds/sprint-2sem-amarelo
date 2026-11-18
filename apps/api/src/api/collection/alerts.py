import logging
from datetime import datetime
from uuid import UUID

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class WebhookAlert:
    def __init__(self, url: SecretStr | None):
        self.url = url

    async def send(self, cycle_id: UUID, started_at: datetime) -> bool:
        # O log é o fallback local; só marcar entregue após resposta HTTP de sucesso.
        logger.error("collection_outage since=%s cycle=%s", started_at.isoformat(), cycle_id)
        if self.url is None or not self.url.get_secret_value():
            logger.warning("collection_alert_destination_not_configured")
            return False
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.post(
                    self.url.get_secret_value(),
                    json={
                        "event": "collection_outage",
                        "cycle_id": str(cycle_id),
                        "started_at": started_at.isoformat(),
                        "text": "Coleta Olho Vivo incompleta há pelo menos dez minutos.",
                    },
                )
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.error("collection_webhook_delivery_failed")
            return False
