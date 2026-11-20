import argparse
import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.collection.alerts import WebhookAlert
from api.collection.runner import CollectionSettings, Collector
from api.collection.source import OlhoVivo
from api.collection.store import PostgresStore, single_collector


async def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor Olho Vivo (US01)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Executar apenas um ciclo")
    mode.add_argument("--test-alert", action="store_true", help="Enviar uma mensagem de teste")
    args = parser.parse_args()
    settings = CollectionSettings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx inclui URL de autenticação em INFO; nunca registrar o token na query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.test_alert:
        sent = await WebhookAlert(
            settings.collection_alert_webhook, settings.collection_alert_format
        ).send(uuid4(), datetime.now(UTC), test=True)
        if not sent:
            raise SystemExit(1)
        logger = logging.getLogger(__name__)
        logger.info("collection_test_alert_delivered")
        return
    if not settings.olhovivo_token.get_secret_value().strip():
        parser.error("configure OLHOVIVO_TOKEN no .env ou no ambiente")
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        async with (
            single_collector(engine) as guard,
            httpx.AsyncClient(
                base_url=settings.olhovivo_base_url + "/",
                timeout=settings.collection_timeout_seconds,
            ) as client,
        ):
            source = OlhoVivo(client, settings.olhovivo_token.get_secret_value())
            store = PostgresStore(
                async_sessionmaker(engine, expire_on_commit=False),
                settings.gtfs_source_id,
                settings.collection_interval_seconds,
            )
            await store.recover_interrupted()
            collector = Collector(source, store, settings, guard=guard)
            success = await collector.run(once=args.once)
            if not success:
                raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).error(
            "collection_process_failed; verifique banco e configuração"
        )
        raise SystemExit(1) from None
