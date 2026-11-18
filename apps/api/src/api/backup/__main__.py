import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.backup.models import BackupRun
from api.backup.service import BackupService, restore
from api.config import Settings
from api.storage.__main__ import archive_from_settings
from api.storage.s3 import S3Archive
from api.storage.service import exclusive

logger = logging.getLogger(__name__)


class BackupSettings(Settings):
    backup_s3_bucket: str = "backup-data"
    backup_s3_endpoint_url: str | None = None
    backup_s3_access_key: str | None = None
    backup_s3_secret_key: str | None = None
    backup_s3_region: str = "us-east-1"
    restore_database_url: SecretStr | None = None
    app_code_version: str | None = None


def backup_from_settings(settings: BackupSettings) -> S3Archive:
    return S3Archive(
        settings.backup_s3_bucket,
        endpoint=settings.backup_s3_endpoint_url,
        region=settings.backup_s3_region,
        access_key=settings.backup_s3_access_key,
        secret_key=settings.backup_s3_secret_key,
    )


def backup_due(last: datetime | None, now: datetime) -> bool:
    cutoff = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < cutoff:
        cutoff -= timedelta(days=1)
    return last is None or last < cutoff


async def main() -> None:
    parser = argparse.ArgumentParser(description="US32: backup e restauração")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Preparar bucket de backup versionado")
    sub.add_parser("run", help="Backup completo, limpeza elegível e retenção")
    sub.add_parser("watch", help="Backup diário às 03:00 UTC, com retomada")
    recover = sub.add_parser("restore")
    recover.add_argument("--manifest-key", required=True)
    recover.add_argument("--target-bucket", required=True)
    recover.add_argument("--target-endpoint")
    recover.add_argument("--map-output", type=Path, required=True)
    args = parser.parse_args()
    settings = BackupSettings()
    backup = backup_from_settings(settings)
    if args.command == "init":
        await asyncio.to_thread(backup.initialize)
        return
    if args.command == "restore":
        if not settings.restore_database_url:
            raise ValueError("RESTORE_DATABASE_URL obrigatória")
        url = settings.restore_database_url.get_secret_value()
        target = S3Archive(
            args.target_bucket,
            endpoint=args.target_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
        )
        engine = create_async_engine(url)
        try:
            result = await restore(
                backup, backup.reference(args.manifest_key), target, engine, url, args.map_output
            )
            print(json.dumps(result))
        finally:
            await engine.dispose()
        return
    version = settings.app_code_version
    if version is None or len(version) != 40 or any(c not in "0123456789abcdef" for c in version):
        raise ValueError("APP_CODE_VERSION exige commit Git completo")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = BackupService(
        sessions, archive_from_settings(settings), backup, settings.database_url
    )
    try:
        async with exclusive(engine, 710132) as guard:
            while True:
                await guard.execute(text("SELECT 1"))
                await guard.commit()
                async with sessions() as session:
                    last = await session.scalar(select(func.max(BackupRun.completed_at)))
                if args.command == "run" or backup_due(last, datetime.now(UTC)):
                    try:
                        ref = await service.create(version)
                        print(ref.model_dump_json(), flush=True)
                    except Exception as exc:
                        logger.error("backup_failed type=%s", type(exc).__name__)
                        if args.command == "run":
                            raise
                        await asyncio.sleep(300)
                        continue
                if args.command == "run":
                    break
                await asyncio.sleep(60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.error("backup_command_failed type=%s", type(exc).__name__)
        raise SystemExit(1) from None
