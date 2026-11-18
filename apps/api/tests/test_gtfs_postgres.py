from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.runner import Collector
from api.collection.source import OlhoVivo, SourceError
from api.collection.store import PostgresStore
from api.gtfs.catalog import Catalog, resolve_version
from api.gtfs.models import GtfsCapture, GtfsVersion
from api.gtfs.source import inspect_feed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection import IsolatedSettings, make_snapshot
from test_collection_postgres import sessions as sessions
from test_collection_resilience import FakeClock
from test_gtfs_source import feed_bytes


async def test_catalog_deduplicates_bytes_but_preserves_each_capture(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = inspect_feed(path)
    catalog = Catalog(sessions)
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    for offset in range(2):
        await catalog.record(
            metadata,
            source_id="sptrans",
            source_url="https://user:password@example.org/feed?key=secret",
            captured_at=now + timedelta(hours=offset),
            bucket="test",
            key="gtfs/one.zip",
        )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GtfsVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(GtfsCapture)) == 2
        capture = await session.scalar(select(GtfsCapture))
        assert capture is not None and capture.source_url == "https://example.org/feed"
        assert await resolve_version(session, date(2026, 11, 18), now) == metadata.sha256
        assert (
            await resolve_version(session, date(2026, 11, 18), now - timedelta(seconds=1)) is None
        )
        assert await resolve_version(session, date(2026, 12, 1), now) is None
        assert await resolve_version(session, date(2026, 11, 18), now, source_id="other") is None


async def test_latest_eligible_version_including_return_to_old_hash(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    catalog = Catalog(sessions)
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    hashes: list[str] = []
    for index, version in enumerate(["one", "two", "one"]):
        path = tmp_path / "feed.zip"
        path.write_bytes(feed_bytes(version=version))
        metadata = inspect_feed(path)
        hashes.append(metadata.sha256)
        await catalog.record(
            metadata,
            source_id="sptrans",
            source_url="https://example.org/feed",
            captured_at=now + timedelta(hours=index),
            bucket="test",
            key=metadata.sha256,
        )
    async with sessions() as session:
        for index in range(3):
            assert (
                await resolve_version(
                    session,
                    now.date(),
                    now + timedelta(hours=index, minutes=1),
                )
                == hashes[index]
            )
        assert hashes[0] == hashes[2] != hashes[1]


@pytest.mark.parametrize("source_id", ["sptrans", "teste-us02"])
async def test_positions_link_by_local_gps_date_and_keep_missing_explicit(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    source_id: str,
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = replace(inspect_feed(path), starts_on=date(2026, 5, 17), ends_on=date(2026, 5, 17))
    known = datetime(2026, 5, 17, tzinfo=UTC)
    await Catalog(sessions).record(
        metadata,
        source_id=source_id,
        source_url="https://example.org/feed",
        captured_at=known,
        bucket="test",
        key=metadata.sha256,
    )
    snapshot = make_snapshot()
    snapshot.collected_at = datetime(2026, 5, 18, 2, tzinfo=UTC)
    # 18/05 UTC ainda é 17/05 em São Paulo.
    snapshot.positions.lines[0].vs[0].ta = snapshot.collected_at
    store = PostgresStore(sessions, gtfs_source_id=source_id)
    cycle = await store.start(snapshot.collected_at)
    await store.save(cycle, snapshot)
    await store.save(cycle, make_snapshot(missing=True))
    async with sessions() as session:
        position = await session.scalar(
            select(VehiclePosition).where(VehiclePosition.prefix == "123")
        )
        assert position is not None
        assert position.gtfs_version_sha256 == metadata.sha256
        assert position.gtfs_link_status == "matched"
        missing = await session.scalar(
            select(VehiclePosition).where(VehiclePosition.gps_at.is_(None))
        )
        assert missing is not None
        assert missing.gtfs_version_sha256 is None
        assert missing.gtfs_link_status == "missing_gps_time"


async def test_no_catalog_is_explicit_and_does_not_drop_positions(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    snapshot = make_snapshot()
    cycle = await store.start(snapshot.collected_at)
    await store.save(cycle, snapshot)
    async with sessions() as session:
        row = await session.scalar(select(VehiclePosition))
        assert row is not None and row.gtfs_version_sha256 is None
        assert row.gtfs_link_status == "no_gtfs_for_date"


async def test_resilient_collection_preserves_gtfs_link_across_garage_retry(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = replace(
        inspect_feed(path),
        starts_on=date(2026, 5, 1),
        ends_on=date(2026, 5, 31),
    )
    await Catalog(sessions).record(
        metadata,
        source_id="sptrans",
        source_url="https://example.org/feed",
        captured_at=datetime(2026, 5, 17, tzinfo=UTC),
        bucket="test",
        key=metadata.sha256,
    )
    source = AsyncMock(spec=OlhoVivo)
    source.snapshot.side_effect = [
        make_snapshot(),
        SourceError("garage_unavailable"),
        make_snapshot(garage=True),
    ]
    collector = Collector(
        source,
        PostgresStore(sessions),
        IsolatedSettings(collection_company_codes=[1], collection_max_retries=1),
        clock=FakeClock(),
    )
    assert await collector.cycle(datetime(2026, 5, 18, tzinfo=UTC))
    assert [call.args for call in source.snapshot.await_args_list] == [(None,), (1,), (1,)]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(CollectionSnapshot)) == 2
        assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 1
        position = await session.scalar(select(VehiclePosition))
        assert position is not None and position.gtfs_version_sha256 == metadata.sha256
        assert position.gtfs_link_status == "matched"
        cycle = await session.scalar(select(CollectionCycle))
        assert cycle is not None and cycle.status == "success"
