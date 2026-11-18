from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.gtfs.models import GtfsCapture, GtfsVersion
from api.gtfs.source import FeedMetadata


def public_source_url(url: str) -> str:
    parts = urlsplit(url)
    # Fonte configurável; nunca persistir usuário/senha, query string ou fragmento.
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


class Catalog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def record(
        self,
        metadata: FeedMetadata,
        *,
        source_id: str,
        source_url: str,
        captured_at: datetime,
        bucket: str,
        key: str,
    ) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                insert(GtfsVersion)
                .values(
                    sha256=metadata.sha256,
                    size=metadata.size,
                    bucket=bucket,
                    object_key=key,
                    starts_on=metadata.starts_on,
                    ends_on=metadata.ends_on,
                    coverage_basis=metadata.coverage_basis,
                    publisher_version=metadata.publisher_version,
                )
                .on_conflict_do_nothing(index_elements=[GtfsVersion.sha256])
            )
            session.add(
                GtfsCapture(
                    id=uuid4(),
                    source_id=source_id,
                    source_url=public_source_url(source_url),
                    captured_at=captured_at,
                    version_sha256=metadata.sha256,
                )
            )


async def resolve_version(
    session: AsyncSession,
    service_date: date,
    known_at: datetime,
    *,
    source_id: str = "sptrans",
) -> str | None:
    """Última referência conhecida na coleta com cobertura para o dia civil local do GPS.

    A cobertura do feed não comprova que uma linha/viagem individual opera nesse dia.
    Não usar uma captura futura para inferir a programação de observações antigas.
    """
    return await session.scalar(
        select(GtfsCapture.version_sha256)
        .join(GtfsVersion, GtfsCapture.version_sha256 == GtfsVersion.sha256)
        .where(
            GtfsCapture.source_id == source_id,
            GtfsCapture.captured_at <= known_at,
            GtfsVersion.starts_on <= service_date,
            GtfsVersion.ends_on >= service_date,
        )
        .order_by(GtfsCapture.captured_at.desc(), GtfsCapture.id.desc())
        .limit(1)
    )
