from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.source import Snapshot
from api.gtfs.catalog import resolve_version


@dataclass
class RecoveryNotice:
    outage: CollectionCycle
    recovered_at: datetime


@asynccontextmanager
async def single_collector(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(710129)"))
        if not acquired:
            raise RuntimeError("collection_already_running")
        try:
            yield connection
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(710129)"))


class PostgresStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        gtfs_source_id: str = "sptrans",
        interval_seconds: int = 30,
    ):
        if not 15 <= interval_seconds <= 60:
            raise ValueError("intervalo deve estar entre 15 e 60 segundos")
        self.sessions = sessions
        self.gtfs_source_id = gtfs_source_id
        self.interval_seconds = interval_seconds

    async def start(self, scheduled_at: datetime, *, cycle_id: UUID | None = None) -> UUID:
        cycle_id = cycle_id or uuid4()
        async with self.sessions.begin() as session:
            session.add(
                CollectionCycle(
                    id=cycle_id,
                    scheduled_at=scheduled_at,
                    status="running",
                    interval_seconds=self.interval_seconds,
                )
            )
        return cycle_id

    async def save(self, cycle_id: UUID, snapshot: Snapshot) -> None:
        snapshot_id = uuid4()
        rows: list[dict[str, Any]] = []
        for line in snapshot.positions.lines:
            for vehicle in line.vs:
                rows.append(
                    dict(
                        id=uuid4(),
                        snapshot_id=snapshot_id,
                        prefix=None if vehicle.p is None else str(vehicle.p),
                        line=line.c,
                        line_code=line.cl,
                        direction=line.sl,
                        latitude=vehicle.py,
                        longitude=vehicle.px,
                        gps_at=vehicle.ta,
                        collected_at=snapshot.collected_at,
                        in_garage=snapshot.company is not None,
                    )
                )
        async with self.sessions.begin() as session:
            versions: dict[date, str | None] = {}
            for row in rows:
                gps_at: datetime | None = row["gps_at"]
                if gps_at is None:
                    row.update(gtfs_version_sha256=None, gtfs_link_status="missing_gps_time")
                    continue
                day = gps_at.astimezone(ZoneInfo("America/Sao_Paulo")).date()
                if day not in versions:
                    versions[day] = await resolve_version(
                        session,
                        day,
                        snapshot.collected_at,
                        source_id=self.gtfs_source_id,
                    )
                version = versions[day]
                row.update(
                    gtfs_version_sha256=version,
                    gtfs_link_status="matched" if version else "no_gtfs_for_date",
                )
            session.add(
                CollectionSnapshot(
                    id=snapshot_id,
                    cycle_id=cycle_id,
                    endpoint=snapshot.endpoint,
                    company=snapshot.company,
                    collected_at=snapshot.collected_at,
                    body=snapshot.body,
                )
            )
            await session.flush()
            # Pequenos lotes respeitam o limite de parâmetros do asyncpg.
            for offset in range(0, len(rows), 500):
                statement = insert(VehiclePosition).values(rows[offset : offset + 500])
                await session.execute(
                    statement.on_conflict_do_nothing(constraint="uq_position_prefix_gps")
                )

    async def finish(self, cycle_id: UUID, status: str, error: str | None = None) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(CollectionCycle)
                .where(CollectionCycle.id == cycle_id)
                .values(status=status, error_code=error, finished_at=datetime.now(UTC))
            )

    async def recover_interrupted(self) -> None:
        """Chamado somente pelo processo que detém o lock exclusivo de coleta."""
        async with self.sessions.begin() as session:
            await session.execute(
                update(CollectionCycle)
                .where(CollectionCycle.status == "running")
                .values(
                    status="interrupted",
                    error_code="process_interrupted",
                    finished_at=datetime.now(UTC),
                )
            )

    async def outage(self) -> CollectionCycle | None:
        """Primeiro ciclo incompleto desde o último sucesso integral, inclusive após reinício."""
        async with self.sessions() as session:
            last_success = await session.scalar(
                select(func.max(CollectionCycle.scheduled_at)).where(
                    CollectionCycle.status == "success"
                )
            )
            statement = select(CollectionCycle).where(
                CollectionCycle.status.in_(["origin_failure", "storage_failure", "interrupted"])
            )
            if last_success is not None:
                statement = statement.where(CollectionCycle.scheduled_at > last_success)
            return await session.scalar(statement.order_by(CollectionCycle.scheduled_at).limit(1))

    async def mark_alerted(self, cycle_id: UUID, when: datetime) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(CollectionCycle)
                .where(CollectionCycle.id == cycle_id)
                .values(alerted_at=when)
            )

    async def record_diagnostics(self, cycle_id: UUID, details: CycleDiagnostics) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(CollectionCycle)
                .where(CollectionCycle.id == cycle_id)
                .values(diagnostics=details.model_dump(mode="json"))
            )

    async def latest_failure(self, since: datetime) -> CollectionCycle | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(CollectionCycle)
                .where(
                    CollectionCycle.scheduled_at >= since,
                    CollectionCycle.status.in_(
                        ["origin_failure", "storage_failure", "interrupted"]
                    ),
                )
                .order_by(CollectionCycle.scheduled_at.desc())
                .limit(1)
            )

    async def pending_recovery(self) -> RecoveryNotice | None:
        success = aliased(CollectionCycle)
        recovered_at = (
            select(func.min(success.finished_at))
            .where(
                success.status == "success",
                success.scheduled_at > CollectionCycle.scheduled_at,
            )
            .correlate(CollectionCycle)
            .scalar_subquery()
        )
        async with self.sessions() as session:
            outage = await session.scalar(
                select(CollectionCycle)
                .where(
                    CollectionCycle.alerted_at.is_not(None),
                    CollectionCycle.recovery_alerted_at.is_(None),
                    recovered_at.is_not(None),
                )
                .order_by(CollectionCycle.scheduled_at)
                .limit(1)
            )
            if outage is None:
                return None
            when = await session.scalar(
                select(func.min(CollectionCycle.finished_at)).where(
                    CollectionCycle.status == "success",
                    CollectionCycle.scheduled_at > outage.scheduled_at,
                )
            )
            return None if when is None else RecoveryNotice(outage, when)

    async def mark_recovery_alerted(self, cycle_id: UUID, when: datetime) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(CollectionCycle)
                .where(CollectionCycle.id == cycle_id)
                .values(recovery_alerted_at=when)
            )
