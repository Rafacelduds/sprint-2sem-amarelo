"""Consome o acervo da US02 sem repetir o download do provedor GTFS."""

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import Settings
from api.gtfs.catalog import resolve_version
from api.gtfs.models import GtfsVersion
from api.storage.__main__ import archive_from_settings
from api.storage.s3 import S3Archive


async def resolve_feed(
    session: AsyncSession, archive: S3Archive, source_id: str, day: date, output: Path
) -> Path | None:
    sha = await resolve_version(session, day, datetime.now(UTC), source_id=source_id)
    version = await session.get(GtfsVersion, sha) if sha else None
    if version is None:
        return None
    if version.bucket != archive.bucket:
        raise ValueError("GTFS catalogado em bucket diferente do configurado")
    reference = archive.reference(version.object_key)
    if reference.sha256 != sha:
        raise ValueError("hash do catálogo GTFS diverge do objeto S3")
    path = output / "gtfs-us02.zip"
    archive.download(reference, path)
    return path


async def load_reference(
    settings: Settings, source_id: str, day: date, output: Path
) -> Path | None:
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            return await resolve_feed(
                session, archive_from_settings(settings), source_id, day, output
            )
    finally:
        await engine.dispose()
