"""Consome o acervo da US02 sem repetir o download do provedor GTFS."""

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import TypeAdapter
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
    # O catálogo US02 não guarda VersionId. A US32 preserva bucket/chave lógicos
    # no dump e mapeia suas identidades versionadas para o objeto recuperado.
    identity_adapter = TypeAdapter(tuple[str, str, str | None])
    restored = [
        ref
        for identity, ref in archive.relocations.items()
        if identity_adapter.validate_json(identity)[:2] == (version.bucket, version.object_key)
    ]
    if restored:
        if any(ref.bucket != archive.bucket for ref in restored):
            raise ValueError("mapa GTFS aponta para bucket diferente do configurado")
        if any(
            ref.sha256 != sha
            or ref.stored_sha256 != sha
            or ref.size != version.size
            or ref.stored_size != version.size
            or ref.encoding != "identity"
            for ref in restored
        ):
            raise ValueError("mapa GTFS diverge do conteúdo catalogado")
        reference = restored[0]
    elif version.bucket == archive.bucket:
        reference = archive.reference(version.object_key)
    else:
        raise ValueError("GTFS em bucket diferente sem mapa de restauração válido")
    if reference.sha256 != sha or reference.size != version.size:
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
