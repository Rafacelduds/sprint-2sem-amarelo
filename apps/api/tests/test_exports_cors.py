import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from api.config import Settings
from api.exports.models import DailyExport
from api.main import create_app
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive


async def test_cross_origin_download_exposes_etag_without_allowing_other_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://localhost:5173"
    payload = b"PAR1-test-payload"
    checksum = hashlib.sha256(payload).hexdigest()
    ref = ObjectRef(
        bucket="private",
        key="derived/test.parquet",
        sha256=checksum,
        stored_sha256=checksum,
        size=len(payload),
        stored_size=len(payload),
    )
    row = DailyExport(day=date(2026, 11, 18), reference=ref.model_dump(mode="json"))
    archive = Mock(spec=S3Archive)

    def download(_: ObjectRef, path: Path) -> None:
        path.write_bytes(payload)

    archive.download.side_effect = download
    monkeypatch.setattr("api.exports.routes.lookup", AsyncMock(return_value=row))

    def configured_archive(_: Settings) -> S3Archive:
        return archive

    monkeypatch.setattr("api.exports.routes.archive_from_settings", configured_archive)
    monkeypatch.setattr("api.main.get_settings", lambda: Settings(cors_origins=[origin]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://api.test"
    ) as client:
        response = await client.get("/exports/raw/2026-11-18/download", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["etag"] == f'"{checksum}"'
        assert response.headers["access-control-allow-origin"] == origin
        exposed = response.headers.get("access-control-expose-headers", "").lower().split(",")
        assert "etag" in {header.strip() for header in exposed}
        rejected = await client.get(
            "/exports/raw/2026-11-18/download", headers={"Origin": "https://untrusted.test"}
        )
        assert "access-control-allow-origin" not in rejected.headers
