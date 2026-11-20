"""Fonte sintética → US01/US02 → US12 → download US09 e relatório US13."""

import hashlib
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import duckdb
import httpx
import pytest
from api.collection.alerts import WebhookAlert
from api.collection.models import CollectionSnapshot, VehiclePosition
from api.collection.runner import Collector
from api.collection.source import OlhoVivo
from api.collection.store import PostgresStore
from api.exports.routes import get_sessions
from api.exports.service import ExportService
from api.gtfs.catalog import Catalog
from api.gtfs.source import inspect_feed
from api.gtfs.storage import S3Archive as GtfsArchive
from api.main import create_app
from api.reliability.service import publish
from api.storage.service import ArchiveService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection import IsolatedSettings
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_gtfs_source import feed_bytes
from test_storage import S3Archive
from test_storage import archive as archive  # noqa: F401


async def test_collection_to_public_download_and_report(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day, code = date(2026, 11, 19), "a" * 40
    at = datetime(2026, 11, 19, 12, tzinfo=UTC)
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = inspect_feed(path)
    key = GtfsArchive(archive.client, archive.bucket).preserve(path, "pipeline", metadata)
    await Catalog(sessions).record(
        metadata,
        source_id="pipeline",
        source_url="https://synthetic.invalid/feed.zip",
        captured_at=at - timedelta(days=1),
        bucket=archive.bucket,
        key=key,
    )
    # Brutos contêm observação repetida e campo não modelado; devem sobreviver byte a byte.
    road = (
        b'{ "l":[{"c":"X-10","cl":1,"sl":1,"vs":[{"p":123,'
        b'"ta":"2026-11-19T11:59:50Z","py":-23.5,"px":-46.6}]}], "extra":null }\n'
    )
    garage = (
        b'{"l":[{"c":"X-10","cl":1,"sl":1,"vs":[{"p":123,'
        b'"ta":"2026-11-19T11:59:50Z","py":-23.5,"px":-46.6}]}]}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("Autenticar"):
            return httpx.Response(200, json=True)
        return httpx.Response(200, content=garage if "Garagem" in request.url.path else road)

    source_datetime = Mock(wraps=datetime)
    source_datetime.now.return_value = at
    monkeypatch.setattr("api.collection.source.datetime", source_datetime)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://synthetic.invalid/v2.1/"
    ) as client:
        collector = Collector(
            OlhoVivo(client, "synthetic"),
            PostgresStore(sessions, "pipeline"),
            IsolatedSettings(collection_company_codes=[5]),
            alert=AsyncMock(spec=WebhookAlert),
        )
        assert await collector.cycle(at)
        assert await collector.cycle(at + timedelta(seconds=30))
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(VehiclePosition)) == 1
        position = await session.scalar(select(VehiclePosition))
        assert position is not None and position.gtfs_version_sha256 == metadata.sha256
        assert position.gtfs_link_status == "matched"
        assert await session.scalar(select(func.count()).select_from(CollectionSnapshot)) == 4
    assert await ArchiveService(sessions, archive).archive_pending() == 4
    result = await ExportService(sessions, archive).publish(day, code)
    assert result is not None and result.snapshots == 4
    report = await publish(
        sessions,
        archive,
        day,
        now=at + timedelta(days=1),
        interval=30,
        source_id="pipeline",
        code_version=code,
    )
    assert report.cycles == 2 and report.gap_seconds > 0
    assert report.gtfs_used[0].sha256 == metadata.sha256
    monkeypatch.setattr("api.db.session.SessionFactory", sessions)
    monkeypatch.setattr("api.exports.routes.archive_from_settings", Mock(return_value=archive))
    app = create_app()
    app.dependency_overrides[get_sessions] = lambda: sessions
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        download = await client.get(f"/exports/raw/{day}/download")
        public_report = await client.get(f"/reports/reliability/{day}")
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == result.reference["sha256"]
    assert public_report.status_code == 200
    assert public_report.json() == report.model_dump(mode="json")
    output = tmp_path / "download.parquet"
    output.write_bytes(download.content)
    with duckdb.connect() as db:
        rows = db.execute("SELECT corpo_original FROM read_parquet(?)", [str(output)]).fetchall()
    assert Counter(row[0] for row in rows) == Counter({road: 2, garage: 2})
