import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from api.backup.__main__ import backup_due
from api.backup.models import BackupReceipt, BackupRun, RecoveryManifest
from api.backup.service import BackupService, restore
from api.collection.models import CollectionSnapshot, VehiclePosition
from api.collection.store import PostgresStore
from api.db.base import Base
from api.storage.contracts import ObjectRef
from api.storage.models import RawObject
from api.storage.s3 import S3Archive
from api.storage.service import ArchiveService
from botocore.exceptions import ClientError
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_collection import make_snapshot
from test_storage import archive as archive  # noqa: F401


@pytest.fixture
async def databases() -> AsyncIterator[tuple[str, str]]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada")
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    names = ["test_backup_" + uuid4().hex for _ in range(2)]
    async with admin.connect() as connection:
        for name in names:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    urls = [
        make_url(url).set(database=name).render_as_string(hide_password=False) for name in names
    ]
    engine = create_async_engine(urls[0])
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
            await connection.execute(text("INSERT INTO alembic_version VALUES ('b32000000001')"))
        yield urls[0], urls[1]
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            for name in names:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest.fixture
def secondary() -> S3Archive:
    endpoint = os.getenv("TEST_BACKUP_S3_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("TEST_BACKUP_S3_ENDPOINT_URL não configurada")
    result = S3Archive(
        "test-backup-" + uuid4().hex, endpoint=endpoint, access_key="test", secret_key="test"
    )
    result.initialize()
    return result


@pytest.mark.asyncio
async def test_full_backup_purges_only_verified_bytes_and_restores(
    databases: tuple[str, str],
    archive: S3Archive,
    secondary: S3Archive,
    tmp_path: Path,
) -> None:
    source_url, target_url = databases
    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)
    sessions = async_sessionmaker(source_engine, expire_on_commit=False)
    target = S3Archive(
        "test-restored-" + uuid4().hex,
        endpoint=os.environ["TEST_S3_ENDPOINT_URL"],
        access_key="test",
        secret_key="test",
    )
    target.initialize()
    try:
        store = PostgresStore(sessions)
        await store.save(await store.start(datetime.now(UTC)), make_snapshot())
        service = ArchiveService(sessions, archive)
        await service.archive_pending()
        async with sessions() as session:
            raw = await session.scalar(select(RawObject))
            assert raw is not None
            original = ObjectRef.model_validate(raw.reference)
            snapshot_id = raw.snapshot_id
        backup = BackupService(sessions, archive, secondary, source_url)
        reference = await backup.create("a" * 40)
        async with sessions() as session:
            snapshot = await session.get(CollectionSnapshot, snapshot_id)
            assert snapshot is not None and snapshot.body is None
            assert snapshot.body_purged_at is not None
            assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 1
        # A restauração não recebe nem depende do cliente de origem.
        archive.client = None
        result = await restore(
            secondary, reference, target, target_engine, target_url, tmp_path / "map.json"
        )
        assert result["objects"] == 1
        assert int(result["elapsed_seconds"]) < 24 * 60 * 60
        target.verify(original)
        restored_sessions = async_sessionmaker(target_engine)
        async with restored_sessions() as session:
            snapshot = await session.get(CollectionSnapshot, snapshot_id)
            assert snapshot is not None and snapshot.body == make_snapshot().body
            assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 1
        with pytest.raises(ValueError, match="não está vazio"):
            await restore(
                secondary, reference, target, target_engine, target_url, tmp_path / "other-map"
            )
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


@pytest.mark.asyncio
async def test_backup_failure_does_not_authorize_cleanup(
    databases: tuple[str, str],
    archive: S3Archive,
    secondary: S3Archive,
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        store = PostgresStore(sessions)
        await store.save(await store.start(datetime.now(UTC)), make_snapshot())
        await ArchiveService(sessions, archive).archive_pending()
        secondary.bucket = "missing-" + uuid4().hex
        backup = BackupService(sessions, archive, secondary, databases[0])
        with pytest.raises(ClientError):
            await backup.create("a" * 40)
        assert await backup.clean_inbox() == 0
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(BackupRun)) == 0
            snapshot = await session.scalar(select(CollectionSnapshot))
            assert snapshot is not None and snapshot.body is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_corruption_blocks_cleanup(
    databases: tuple[str, str],
    archive: S3Archive,
    secondary: S3Archive,
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        store = PostgresStore(sessions)
        await store.save(await store.start(datetime.now(UTC)), make_snapshot())
        await ArchiveService(sessions, archive).archive_pending()
        service = BackupService(sessions, archive, secondary, databases[0])
        await service.create("a" * 40)
        async with sessions.begin() as session:
            receipt = await session.scalar(select(BackupReceipt))
            snapshot = await session.scalar(select(CollectionSnapshot))
            assert receipt is not None and snapshot is not None
            snapshot.body = make_snapshot().body
            copied = ObjectRef.model_validate(receipt.backup_reference)
        secondary.client.delete_object(
            Bucket=secondary.bucket, Key=copied.key, VersionId=copied.version_id
        )
        with pytest.raises(ClientError):
            await service.clean_inbox()
        async with sessions() as session:
            snapshot = await session.scalar(select(CollectionSnapshot))
            assert snapshot is not None and snapshot.body is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retention_keeps_seven_recovery_points_and_all_raw(
    databases: tuple[str, str],
    archive: S3Archive,
    secondary: S3Archive,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        path = tmp_path / "raw"
        path.write_bytes(b"source-data")
        ref = archive.put(path, "raw/source")
        service = BackupService(sessions, archive, secondary, databases[0])
        for _ in range(8):
            await service.create("a" * 40)
        assert len(list(secondary.objects("backups/database/"))) == 7
        assert len(list(secondary.objects("backups/runs/"))) == 7
        archive.verify(ref)
        secondary.verify(secondary.reference(ref.key))
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(BackupRun)
                    .where(BackupRun.expired_at.is_(None))
                )
                == 7
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_backup_object_blocks_restore_without_loading_database(
    databases: tuple[str, str],
    archive: S3Archive,
    secondary: S3Archive,
    tmp_path: Path,
) -> None:
    source_engine = create_async_engine(databases[0])
    target_engine = create_async_engine(databases[1])
    sessions = async_sessionmaker(source_engine, expire_on_commit=False)
    target = S3Archive(
        "test-empty-" + uuid4().hex,
        endpoint=os.environ["TEST_S3_ENDPOINT_URL"],
        access_key="test",
        secret_key="test",
    )
    target.initialize()
    try:
        path = tmp_path / "source"
        path.write_bytes(b"source")
        archive.put(path, "raw/missing-after-backup")
        service = BackupService(sessions, archive, secondary, databases[0])
        ref = await service.create("a" * 40)
        manifest_path = tmp_path / "manifest"
        secondary.download(ref, manifest_path)
        manifest = RecoveryManifest.model_validate_json(manifest_path.read_bytes())
        copied = manifest.objects[0].backup
        secondary.client.delete_object(
            Bucket=secondary.bucket, Key=copied.key, VersionId=copied.version_id
        )
        with pytest.raises(ClientError):
            await restore(
                secondary, ref, target, target_engine, databases[1], tmp_path / "restore-map"
            )
        async with target_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
                    )
                )
                == 0
            )
        assert not (tmp_path / "restore-map").exists()
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


def test_schedule_catches_up_once_and_runs_at_0300_utc() -> None:
    now = datetime(2026, 11, 19, 2, tzinfo=UTC)
    assert backup_due(None, now)
    assert not backup_due(datetime(2026, 11, 18, 4, tzinfo=UTC), now)
    assert backup_due(datetime(2026, 11, 18, 4, tzinfo=UTC), datetime(2026, 11, 19, 3, tzinfo=UTC))
