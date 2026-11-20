import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.store import PostgresStore, single_collector
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


@pytest.mark.asyncio
async def test_outage_and_delivered_alert_survive_restart_and_close_on_recovery(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    started = datetime.now(UTC) - timedelta(minutes=11)
    failed = await store.start(started)
    await store.finish(failed, "origin_failure", "timeout")
    restarted = PostgresStore(sessions)
    outage = await restarted.outage()
    assert outage is not None and outage.id == failed and outage.alerted_at is None
    await restarted.mark_alerted(failed, datetime.now(UTC))
    outage = await PostgresStore(sessions).outage()
    assert outage is not None and outage.alerted_at is not None
    recovered = await restarted.start(datetime.now(UTC))
    await restarted.finish(recovered, "success")
    assert await restarted.outage() is None
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 0


@pytest.mark.asyncio
async def test_process_interruption_becomes_gap_without_synthesizing_positions(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    interrupted = await store.start(datetime.now(UTC))
    await store.recover_interrupted()
    async with sessions() as session:
        cycle = await session.get(CollectionCycle, interrupted)
        assert cycle is not None and cycle.status == "interrupted"
        assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 0


@pytest.mark.asyncio
async def test_only_one_collector_can_hold_database_lock() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada")
    engine = create_async_engine(url)
    try:
        async with single_collector(engine):
            with pytest.raises(RuntimeError, match="collection_already_running"):
                async with single_collector(engine):
                    pytest.fail("Lock não impediu a segunda instância")
        async with single_collector(engine):
            pass  # lock liberado após saída do primeiro processo
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_stays_pending_across_restart_until_delivery_confirmed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    started = datetime.now(UTC) - timedelta(minutes=12)
    outage_id = await store.start(started)
    details = CycleDiagnostics(
        status="origin_failure",
        rounds=6,
        road_saved=True,
        garages_saved=8,
        companies_discovered=True,
        failures={"company_600": "http_500"},
    )
    await store.record_diagnostics(outage_id, details)
    await store.finish(outage_id, "origin_failure", "http_500")
    await store.mark_alerted(outage_id, started + timedelta(minutes=10))
    assert await store.pending_recovery() is None
    partial = await store.start(started + timedelta(minutes=11))
    await store.finish(partial, "origin_failure", "still_partial")
    assert await store.pending_recovery() is None
    success = await store.start(datetime.now(UTC))
    await store.finish(success, "success")
    restarted = PostgresStore(sessions)
    notice = await restarted.pending_recovery()
    assert notice is not None and notice.outage.id == outage_id
    assert notice.outage.diagnostics == details.model_dump()
    assert (await PostgresStore(sessions).pending_recovery()) is not None
    await restarted.mark_recovery_alerted(outage_id, datetime.now(UTC))
    assert await PostgresStore(sessions).pending_recovery() is None


@pytest.mark.asyncio
async def test_no_recovery_for_outage_that_never_delivered_an_alert(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    outage_id = await store.start(datetime.now(UTC) - timedelta(minutes=12))
    await store.finish(outage_id, "origin_failure")
    success = await store.start(datetime.now(UTC))
    await store.finish(success, "success")
    assert await store.pending_recovery() is None
