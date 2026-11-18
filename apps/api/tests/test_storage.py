import gzip
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote
from uuid import uuid4

import pytest
from api.collection.models import CollectionSnapshot
from api.collection.store import PostgresStore
from api.storage.__main__ import inventory_bytes
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.models import ProcessingRun, RawObject
from api.storage.s3 import CollisionError, S3Archive
from api.storage.service import ArchiveService, exclusive
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_collection import make_snapshot
from test_collection_postgres import sessions as sessions  # noqa: F401


@pytest.fixture
def archive() -> S3Archive:
    endpoint = os.getenv("TEST_S3_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("TEST_S3_ENDPOINT_URL não configurada")
    result = S3Archive(
        "test-archive-" + uuid4().hex, endpoint=endpoint, access_key="test", secret_key="test"
    )
    result.initialize()
    return result


def test_gzip_preserves_bytes_collision_and_idempotent_resume(
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    path = tmp_path / "input"
    payload = b'{ "unknown": [1, null], "l": [], "hr": "11:00" }\n'
    path.write_bytes(payload)
    ref = archive.put(path, "raw/test.json.gz", compress=True)
    target = tmp_path / "download"
    archive.download(ref, target)
    assert gzip.decompress(target.read_bytes()) == payload
    assert ref.sha256 != ref.stored_sha256
    with pytest.raises(CollisionError):
        archive.put(path, ref.key, compress=True)
    assert archive.put(path, ref.key, compress=True, resume=True) == ref
    path.write_bytes(b"other")
    with pytest.raises(CollisionError):
        archive.put(path, ref.key, compress=True, resume=True)
    archive.verify(ref)


def test_concurrent_writers_cannot_overwrite(archive: S3Archive, tmp_path: Path) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"same input")

    def write(_: int) -> bool:
        try:
            archive.put(path, "raw/race")
            return True
        except CollisionError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [1, 2])) == [False, True]


@pytest.mark.asyncio
async def test_archive_inbox_retry_and_provenance(
    archive: S3Archive,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store = PostgresStore(sessions)
    cycle = await store.start(datetime.now(UTC))
    await store.save(cycle, make_snapshot())
    async with sessions() as session:
        snapshot = await session.scalar(select(CollectionSnapshot))
        assert snapshot is not None
        snapshot_id = snapshot.id
    service = ArchiveService(sessions, archive)
    assert await service.archive_pending() == 1
    assert await service.archive_pending() == 0
    async with sessions() as session:
        raw = await session.get(RawObject, snapshot_id)
        assert raw is not None
        ref = ObjectRef.model_validate(raw.reference)
        # Simular upload concluído seguido de rollback do catálogo.
        await session.delete(raw)
        await session.commit()
    assert await service.archive_pending() == 1
    path = tmp_path / "output"
    output_bytes = inventory_bytes([ref])
    path.write_bytes(output_bytes)
    output = archive.put(path, "derived/inventory/example.json", content_type="application/json")
    manifest = ProcessingManifest(
        run_id=uuid4(),
        dataset="technical-example",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        code_version="a" * 40,
        rule_version="inventory-v1",
        inputs=[ref],
        outputs=[output],
    )
    recorded = await service.record(manifest)
    assert await service.record(manifest) == recorded
    assert output_bytes == inventory_bytes([ref])
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingRun)) == 1
    wrong = ref.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="hash original"):
        await service.record(manifest.model_copy(update={"run_id": uuid4(), "inputs": [wrong]}))


@pytest.mark.asyncio
async def test_s3_failure_keeps_inbox_for_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresStore(sessions)
    await store.save(await store.start(datetime.now(UTC)), make_snapshot())
    unavailable = S3Archive(
        "missing", endpoint="http://127.0.0.1:1", access_key="test", secret_key="test"
    )
    # Curto timeout para demonstrar falha de transporte sem espera das retentativas do SDK.
    from typing import Any, cast

    import boto3
    from botocore.config import Config

    unavailable.client = cast(Any, boto3).client(
        "s3",
        endpoint_url="http://127.0.0.1:1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(retries={"max_attempts": 0}),
    )
    from botocore.exceptions import EndpointConnectionError

    with pytest.raises(EndpointConnectionError):
        await ArchiveService(sessions, unavailable).archive_pending()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(RawObject)) == 0
        snapshot = await session.scalar(select(CollectionSnapshot))
        assert snapshot is not None and snapshot.body == make_snapshot().body


@pytest.mark.asyncio
async def test_history_is_preserved_and_import_is_repeatable(
    archive: S3Archive,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    path = tmp_path / "2026-05-01.parquet"
    path.write_bytes(b"PAR1historical-sourcePAR1")
    service = ArchiveService(sessions, archive)
    first = await service.import_file(path, "gps-maio-2026")
    assert await service.import_file(path, "gps-maio-2026") == first
    assert "captured-at" not in first.metadata
    assert path.read_bytes() == b"PAR1historical-sourcePAR1"


def test_download_rejects_wrong_stored_hash(archive: S3Archive, tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"original")
    ref = archive.put(source, "raw/original")
    corrupt = ref.model_copy(update={"stored_sha256": "0" * 64})
    with pytest.raises(ValueError, match="hash armazenado"):
        archive.verify(corrupt)


def test_provenance_requires_versions_and_timezone() -> None:
    with pytest.raises(ValidationError):
        ProcessingManifest.model_validate(
            {
                "run_id": str(uuid4()),
                "dataset": "x",
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "code_version": "",
                "rule_version": "",
                "inputs": [],
                "outputs": [],
            }
        )


@pytest.mark.asyncio
async def test_archive_guard_survives_commit_without_holding_open_transaction() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada")
    engine = create_async_engine(url)
    try:
        async with exclusive(engine, 710112) as guard:
            assert not guard.in_transaction()
            with pytest.raises(RuntimeError, match="já está"):
                async with exclusive(engine, 710112):
                    pytest.fail("segunda instância adquiriu o lock")
        async with exclusive(engine, 710112):
            pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["gps maio.parquet", "gps ação %.parquet"])
async def test_import_special_filename_and_resume(
    archive: S3Archive,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    name: str,
) -> None:
    path = tmp_path / name
    path.write_bytes(b"PAR1receivedPAR1")
    service = ArchiveService(sessions, archive)
    ref = await service.import_file(path, "history")
    assert ref.key.endswith("/" + quote(name, safe=""))
    async with sessions.begin() as session:
        raw = await session.scalar(select(RawObject).where(RawObject.key == ref.key))
        assert raw is not None
        await session.delete(raw)
    # Upload já existe, mas o catálogo precisa ser reconstruído.
    assert await service.import_file(path, "history") == ref
    assert await service.import_file(path, "history") == ref
    archive.verify(ref)
    assert path.read_bytes() == b"PAR1receivedPAR1"


def test_invalid_key_is_rejected_before_upload(tmp_path: Path) -> None:
    archive = S3Archive("test", access_key="test", secret_key="test")
    client = Mock()
    archive.client = client
    path = tmp_path / "input"
    path.write_bytes(b"received")
    with pytest.raises(ValidationError):
        archive.put(path, "invalid-prefix/name")
    client.put_object.assert_not_called()
