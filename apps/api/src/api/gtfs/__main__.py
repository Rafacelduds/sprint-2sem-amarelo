import argparse
import asyncio
import logging
from urllib.parse import urlsplit

import boto3
import httpx
from botocore.config import Config
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.gtfs.catalog import Catalog
from api.gtfs.runner import GtfsCollector, GtfsSettings
from api.gtfs.storage import S3Archive


async def main() -> None:
    parser = argparse.ArgumentParser(description="Captura e versionamento GTFS (US02)")
    parser.add_argument("--once", action="store_true", help="Executar uma captura e encerrar")
    args = parser.parse_args()
    try:
        settings = GtfsSettings()
    except ValidationError:
        parser.error("configuração inválida; confira as variáveis GTFS, S3 e DATABASE_URL")
    url = urlsplit(settings.gtfs_source_url.get_secret_value())
    if url.scheme not in {"http", "https"} or not url.hostname:
        parser.error("configure GTFS_SOURCE_URL com a URL HTTP(S) autorizada do ZIP")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        # O overload global inclui serviços cujos stubs opcionais não instalamos.
        s3 = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3},
                request_checksum_calculation="when_required",
            ),
        )
        async with httpx.AsyncClient(
            timeout=settings.gtfs_timeout_seconds,
            follow_redirects=True,
        ) as client:
            collector = GtfsCollector(
                client,
                S3Archive(s3, settings.s3_bucket),
                Catalog(async_sessionmaker(engine, expire_on_commit=False)),
                settings,
            )
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
        logging.getLogger(__name__).error("gtfs_startup_failed; confira configuração e serviços")
        raise SystemExit(1) from None
