import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import duckdb
import httpx
import pytest
from api.collection.models import CollectionCycle, CollectionSnapshot
from api.config import Settings
from api.exports.__main__ import run_cycle
from api.exports.contract import DICTIONARY, LICENSE, SOURCE, ZONE, bounds, deadline
from api.exports.models import DailyExport
from api.exports.routes import get_sessions
from api.exports.service import ExportService, PendingArchive
from api.main import create_app
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.service import ArchiveService
from botocore.exceptions import ClientError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_storage import S3Archive
from test_storage import archive as archive  # noqa: F401

DAY = date(2026, 5, 18)
CODE = "a" * 40
BODY = b'{ "hr": "00:00", "l": [], "unknown": [null, "a\\u00e7ao"] }\n'


async def seed(
    sessions: async_sessionmaker[AsyncSession],
    instant: datetime,
    body: bytes = BODY,
    company: int | None = None,
) -> UUID:
    identity, cycle = uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add(CollectionCycle(id=cycle, scheduled_at=instant, status="success"))
        await session.flush()
        session.add(
            CollectionSnapshot(
                id=identity,
                cycle_id=cycle,
                collected_at=instant,
                endpoint="/Posicao" if company is None else "/Posicao/Garagem",
                company=company,
                body=body,
            )
        )
    return identity


def test_civil_day_timezone_and_deadline() -> None:
    assert bounds(DAY) == (
        datetime(2026, 5, 18, 3, tzinfo=UTC),
        datetime(2026, 5, 19, 3, tzinfo=UTC),
    )
    assert deadline(DAY) == datetime(2026, 5, 19, 6, tzinfo=ZONE)
    # O histórico de horário de verão também respeita a zona, sem fixar UTC-3.
    assert bounds(date(2018, 12, 1))[0].hour == 2


async def test_parquet_preserves_raw_bytes_metadata_midnight_and_garage(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    start, end = bounds(DAY)
    before = await seed(sessions, start - timedelta(microseconds=1))
    first = await seed(sessions, start)
    garage = await seed(sessions, end - timedelta(microseconds=1), b'{"l":[],"extra":42}', 5)
    after = await seed(sessions, end)
    await ArchiveService(sessions, archive).archive_pending()
    service = ExportService(sessions, archive)
    assert await service.candidates(DAY + timedelta(days=1)) == [DAY - timedelta(days=1), DAY]
    result = await service.publish(DAY, CODE)
    assert result is not None and result.snapshots == 2
    path = tmp_path / "result.parquet"
    await asyncio.to_thread(archive.download, ObjectRef.model_validate(result.reference), path)
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT captura_id, ciclo_id, epoch_us(coletado_em), endpoint, empresa, "
            "fonte, sha256_original, corpo_original FROM read_parquet(?) ORDER BY coletado_em",
            [str(path)],
        ).fetchall()
        assert [r[0] for r in rows] == [str(first), str(garage)]
        assert all(r[0] not in [str(before), str(after)] for r in rows)
        assert rows[0][-1] == BODY
        assert rows[0][-2] == hashlib.sha256(BODY).hexdigest()
        assert rows[0][2] == int(start.timestamp() * 1_000_000)
        assert rows[1][4] == 5 and rows[0][4] is None
        assert rows[0][5] == SOURCE
        metadata = dict(
            connection.execute(
                "SELECT decode(key), decode(value) FROM parquet_kv_metadata(?)", [str(path)]
            ).fetchall()
        )
    assert metadata["license"] == LICENSE
    assert metadata["license_name"] == "CC BY 4.0"
    assert metadata["source"] == SOURCE
    assert json.loads(metadata["data_dictionary"]) == DICTIONARY
    manifest_path = tmp_path / "manifest.json"
    archive.download(ObjectRef.model_validate(result.manifest), manifest_path)
    manifest = ProcessingManifest.model_validate_json(manifest_path.read_bytes())
    assert manifest.code_version == CODE and len(manifest.inputs) == 2
    assert all(ref.key.startswith("raw/") for ref in manifest.inputs)
    assert manifest.outputs[0].sha256 == result.reference["sha256"]


async def test_pending_archive_never_replaces_publication_and_late_data_revises(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
) -> None:
    start, _ = bounds(DAY)
    identity = await seed(sessions, start)
    service = ExportService(sessions, archive)
    with pytest.raises(PendingArchive):
        await service.publish(DAY, CODE)
    async with sessions() as session:
        assert await session.get(DailyExport, DAY) is None
    await ArchiveService(sessions, archive).archive_pending()
    first = await service.publish(DAY, CODE)
    assert first is not None
    # Funciona mesmo após a limpeza da inbox: lê os originais arquivados.
    async with sessions.begin() as session:
        await session.execute(
            update(CollectionSnapshot)
            .where(CollectionSnapshot.id == identity)
            .values(body=None, body_purged_at=datetime.now(UTC))
        )
    same = await service.publish(DAY, CODE)
    assert same is not None and same.reference == first.reference
    assert same.published_at == first.published_at
    await seed(sessions, start + timedelta(seconds=30), b'{"l":[]}')
    assert DAY in await service.candidates(DAY + timedelta(days=1))
    with pytest.raises(PendingArchive):
        await service.publish(DAY, CODE)
    async with sessions() as session:
        current = await session.get(DailyExport, DAY)
        assert current is not None and current.reference == first.reference
    await ArchiveService(sessions, archive).archive_pending()
    second = await service.publish(DAY, CODE)
    assert second is not None and second.snapshots == 2 and second.reference != first.reference
    archive.verify(ObjectRef.model_validate(first.reference))
    archive.verify(ObjectRef.model_validate(second.reference))
    assert DAY not in await service.candidates(DAY + timedelta(days=1))


async def test_no_data_current_day_and_invalid_code(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
) -> None:
    service = ExportService(sessions, archive)
    assert await service.publish(DAY, CODE) is None
    with pytest.raises(ValueError, match="encerrados"):
        await service.publish(datetime.now(ZONE).date(), CODE)
    await seed(sessions, bounds(DAY)[0])
    await ArchiveService(sessions, archive).archive_pending()
    with pytest.raises(ValueError, match="commit"):
        await service.publish(DAY, "main")
    assert list(archive.objects("derived/public-raw/")) == []


async def test_corrupted_raw_fails_without_publishing(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
) -> None:
    await seed(sessions, bounds(DAY)[0])
    await ArchiveService(sessions, archive).archive_pending()
    # Remover a versão original para simular arquivo indisponível.
    ref = next(archive.objects("raw/"))
    archive.client.delete_object(Bucket=ref.bucket, Key=ref.key, VersionId=ref.version_id)
    with pytest.raises(ClientError):
        await ExportService(sessions, archive).publish(DAY, CODE)
    async with sessions() as session:
        assert await session.get(DailyExport, DAY) is None


async def test_public_http_catalog_download_pagination_and_restore_map(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed(sessions, bounds(DAY)[0])
    await ArchiveService(sessions, archive).archive_pending()
    result = await ExportService(sessions, archive).publish(DAY, CODE)
    assert result is not None
    app = create_app()
    app.dependency_overrides[get_sessions] = lambda: sessions

    def configured_archive(_: Settings) -> S3Archive:
        return archive

    monkeypatch.setattr("api.exports.routes.archive_from_settings", configured_archive)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/exports/raw")
        assert response.status_code == 200
        assert response.json()[0]["dia"] == DAY.isoformat()
        assert response.json()[0]["publicado_no_prazo"] is False
        assert "bucket" not in response.text and "reference" not in response.text
        assert (await client.get("/exports/raw", params={"before": DAY.isoformat()})).json() == []
        assert (await client.get("/exports/raw?limit=367")).status_code == 422
        assert (await client.get("/exports/raw/not-a-date")).status_code == 422
        assert (await client.get("/exports/raw/2026-01-01")).status_code == 404
        assert (await client.get("/exports/raw/2026-01-01/download")).status_code == 404
        assert (await client.get("/exports/raw/dictionary")).json() == DICTIONARY
        assert (await client.get(f"/exports/raw/{DAY}")).status_code == 200
        download = await client.get(f"/exports/raw/{DAY}/download")
        assert download.status_code == 200
        assert hashlib.sha256(download.content).hexdigest() == result.reference["sha256"]
        assert "attachment" in download.headers["content-disposition"]
        assert LICENSE in download.headers["link"]
        # Simular US32: mesma identidade lógica em outra chave/versão física.
        old = ObjectRef.model_validate(result.reference)
        path = tmp_path / "copy.parquet"
        archive.download(old, path)
        relocated = archive.put(path, "derived/restored.parquet")
        archive.relocations[archive.identity(old)] = relocated
        archive.client.delete_object(Bucket=old.bucket, Key=old.key, VersionId=old.version_id)
        assert (await client.get(f"/exports/raw/{DAY}/download")).content == download.content
        archive.relocations.clear()
        failed = await client.get(f"/exports/raw/{DAY}/download")
        assert failed.status_code == 503 and old.key not in failed.text


async def test_cycle_continues_after_failed_day_and_retries() -> None:
    service = AsyncMock(spec=ExportService)
    service.candidates.return_value = [DAY, DAY + timedelta(days=1)]
    service.publish.side_effect = [PendingArchive(), None]
    assert not await run_cycle(service, CODE)
    assert service.publish.await_count == 2
    service.publish.side_effect = None
    service.publish.return_value = None
    assert await run_cycle(service, CODE)


async def test_interrupted_publication_resumes_same_immutable_output(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed(sessions, bounds(DAY)[0])
    await ArchiveService(sessions, archive).archive_pending()
    record = ArchiveService.record

    async def fail(*_: object) -> ObjectRef:
        raise RuntimeError("simular interrupção entre upload e catálogo")

    monkeypatch.setattr(ArchiveService, "record", fail)
    service = ExportService(sessions, archive)
    with pytest.raises(RuntimeError, match="interrupção"):
        await service.publish(DAY, CODE)
    orphan = next(archive.objects("derived/public-raw/"))
    async with sessions() as session:
        assert await session.get(DailyExport, DAY) is None
    monkeypatch.setattr(ArchiveService, "record", record)
    result = await service.publish(DAY, CODE)
    assert result is not None and result.reference["sha256"] == orphan.sha256
    assert result.reference["version_id"] == orphan.version_id
