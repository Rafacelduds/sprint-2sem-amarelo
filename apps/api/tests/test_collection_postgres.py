import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.store import PostgresStore
from api.db.base import Base
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_collection import make_snapshot


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada: requer PostgreSQL de testes")
    schema = "test_collection_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
async def test_repeated_observations_survive_restart_without_duplicates(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    cycle = await store.start(datetime.now(UTC))
    snapshot = make_snapshot()
    await store.save(cycle, snapshot)
    # Simula outra instância/reinício e conflito entre operação e garagem.
    restarted = PostgresStore(sessions)
    await restarted.save(cycle, make_snapshot(garage=True))
    await restarted.finish(cycle, "success")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 1
        assert await session.scalar(select(func.count()).select_from(CollectionSnapshot)) == 2
        row = await session.scalar(select(VehiclePosition))
        assert row is not None and row.prefix == "123" and row.latitude == -23.5
        assert row.gps_at == datetime(2026, 5, 18, 12, tzinfo=UTC)
        saved = await session.get(CollectionSnapshot, row.snapshot_id)
        assert saved is not None and saved.body == snapshot.body
        status = await session.get(CollectionCycle, cycle)
        assert status is not None and status.status == "success"


@pytest.mark.asyncio
async def test_missing_fields_are_null_and_not_false_duplicates(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    cycle = await store.start(datetime.now(UTC))
    await store.save(cycle, make_snapshot(missing=True, garage=True))
    await store.save(cycle, make_snapshot(missing=True, garage=True))
    async with sessions() as session:
        rows = (await session.scalars(select(VehiclePosition))).all()
        assert len(rows) == 2
        assert all(
            row.prefix is None and row.gps_at is None and row.latitude is None for row in rows
        )
        assert all(row.in_garage for row in rows)
