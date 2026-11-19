import argparse
import asyncio
import logging

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.collection.runner import CollectionSettings, Collector
from api.collection.source import OlhoVivo
from api.collection.store import PostgresStore, single_collector


async def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor Olho Vivo (US01)")
    parser.add_argument("--once", action="store_true", help="Executar apenas um ciclo")
    args = parser.parse_args()
    settings = CollectionSettings()
    if not settings.olhovivo_token.get_secret_value().strip():
        parser.error("configure OLHOVIVO_TOKEN no .env ou no ambiente")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx inclui URL de autenticação em INFO; nunca registrar o token na query string.
    logging.getLogger("httpx").setLevel(logging.WARNING)
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
