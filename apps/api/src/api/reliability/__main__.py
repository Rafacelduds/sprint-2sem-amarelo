import argparse
import asyncio
import os
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.collection.runner import CollectionSettings
from api.config import get_settings
from api.reliability.service import LOCAL, publish
from api.storage.__main__ import archive_from_settings


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="US13: publicar relatório diário de confiabilidade"
    )
    parser.add_argument("--day", type=date.fromisoformat, help="Dia civil YYYY-MM-DD; ontem")
    parser.add_argument("--legacy-interval", type=int, choices=range(15, 61), default=None)
    parser.add_argument("--code-version", default=os.getenv("APP_CODE_VERSION") or "working-tree")
    parser.add_argument("--watch", action="store_true", help="Atualizar ontem e hoje continuamente")
    parser.add_argument("--refresh-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.refresh_seconds < 60 or (args.watch and args.day):
        parser.error("atualização mínima de 60 s; --watch não aceita --day")
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    archive = archive_from_settings(settings)
    try:
        while True:
            now = datetime.now(LOCAL)
            days = [args.day or now.date() - timedelta(days=1)]
            if args.watch:
                days.append(now.date())
            for day in days:
                try:
                    report = await publish(
                        async_sessionmaker(engine),
                        archive,
                        day,
                        now=now,
                        interval=args.legacy_interval
                        or CollectionSettings().collection_interval_seconds,
                        source_id=settings.gtfs_source_id,
                        code_version=args.code_version,
                    )
                    print(report.model_dump_json(indent=None if args.watch else 2), flush=True)
                except Exception as exc:
                    message = f"US13 falhou: {type(exc).__name__}; relatório anterior preservado\n"
                    if not args.watch:
                        parser.exit(1, message)
                    print(message, flush=True)
            if not args.watch:
                break
            await asyncio.sleep(args.refresh_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
