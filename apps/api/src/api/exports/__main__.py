import argparse
import asyncio
import logging
import os
import re
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import get_settings
from api.exports.contract import ZONE
from api.exports.service import ExportService
from api.storage.__main__ import archive_from_settings
from api.storage.service import exclusive

logger = logging.getLogger(__name__)


async def run_cycle(service: ExportService, code_version: str, day: date | None = None) -> bool:
    success = True
    days = [day] if day is not None else await service.candidates(datetime.now(ZONE).date())
    for candidate in days:
        try:
            result = await service.publish(candidate, code_version)
            logger.info("export day=%s snapshots=%s", candidate, result.snapshots if result else 0)
        except Exception as exc:
            # Um dia pendente não impede os seguintes. Não expor URLs/credenciais em erros.
            logger.error("export_failed day=%s type=%s", candidate, type(exc).__name__)
            success = False
    return success


async def main() -> None:
    parser = argparse.ArgumentParser(description="US09: publicar dias encerrados em Parquet")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--code-version", default=os.getenv("APP_CODE_VERSION", ""))
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.code_version):
        parser.error("informe --code-version ou APP_CODE_VERSION com o commit Git completo")
    if args.watch and args.day:
        parser.error("--day é pontual; use --watch sem --day para retomada automática")
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    service = ExportService(
        async_sessionmaker(engine, expire_on_commit=False), archive_from_settings(settings)
    )
    try:
        async with exclusive(engine, 710109) as guard:
            while True:
                await guard.execute(text("SELECT 1"))
                await guard.commit()
                try:
                    success = await run_cycle(service, args.code_version, args.day)
                except Exception as exc:
                    logger.error("export_cycle_failed type=%s", type(exc).__name__)
                    success = False
                if not args.watch:
                    if not success:
                        raise RuntimeError("publicação pendente; verifique arquivamento e serviços")
                    return
                await asyncio.sleep(300)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.error("export_stopped type=%s", type(exc).__name__)
        raise SystemExit(1) from None
