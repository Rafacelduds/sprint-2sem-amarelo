"""Evidência persistida pelo job, sem inferir atividade pela existência de backups."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.backup.models import BackupAttempt, BackupWorker
from api.backup.service import BackupService
from api.storage.contracts import ObjectRef

HEARTBEAT_SECONDS = 30
STALE_SECONDS = 120


def cutoff(now: datetime) -> datetime:
    due = now.astimezone(UTC).replace(hour=3, minute=0, second=0, microsecond=0)
    return due if now >= due else due - timedelta(days=1)


def backup_due(last: datetime | None, now: datetime) -> bool:
    return last is None or last < cutoff(now)


async def pulse(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions.begin() as session:
        statement = insert(BackupWorker).values(id="daily", heartbeat_at=datetime.now(UTC))
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[BackupWorker.id],
                set_={"heartbeat_at": statement.excluded.heartbeat_at},
            )
        )


async def heartbeat(sessions: async_sessionmaker[AsyncSession]) -> None:
    while True:
        await pulse(sessions)
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def record_attempt(service: BackupService, version: str) -> ObjectRef:
    identity = uuid4()
    async with service.sessions.begin() as session:
        session.add(BackupAttempt(id=identity, started_at=datetime.now(UTC), status="running"))
    try:
        ref = await service.create(version)
    except BaseException:
        # Não persistir exceções, URLs, credenciais nem os argumentos do pg_dump.
        async with service.sessions.begin() as session:
            await session.execute(
                update(BackupAttempt)
                .where(BackupAttempt.id == identity)
                .values(status="failed", finished_at=datetime.now(UTC))
            )
        raise
    async with service.sessions.begin() as session:
        await session.execute(
            update(BackupAttempt)
            .where(BackupAttempt.id == identity)
            .values(
                status="success",
                finished_at=datetime.now(UTC),
                backup_id=UUID(ref.key.rsplit("/", 1)[1][:-5]),
            )
        )
    return ref
