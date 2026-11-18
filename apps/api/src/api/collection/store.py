from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.source import Snapshot


class PostgresStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def start(self, scheduled_at: datetime) -> UUID:
        cycle_id = uuid4()
        async with self.sessions.begin() as session:
            session.add(CollectionCycle(id=cycle_id, scheduled_at=scheduled_at, status="running"))
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
