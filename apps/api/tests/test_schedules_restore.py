import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from api.config import Settings
from api.gtfs.catalog import Catalog
from api.gtfs.models import GtfsVersion
from api.gtfs.source import inspect_feed
from api.gtfs.storage import S3Archive as GtfsArchive
from api.schedules.catalog import resolve_feed
from api.storage.__main__ import archive_from_settings
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_schedules import feed
from test_storage import archive as archive  # noqa: F401


async def test_gtfs_catalog_uses_restored_map_and_verifies_download(
    sessions: async_sessionmaker[AsyncSession], archive: S3Archive, tmp_path: Path
) -> None:
    path = feed(tmp_path / "feed.zip", daily=True)
    metadata = inspect_feed(path)
    key = GtfsArchive(archive.client, archive.bucket).preserve(path, "test-us04", metadata)
    original = archive.reference(key)
    await Catalog(sessions).record(
        metadata,
        source_id="test-us04",
        source_url="https://example.org/feed.zip",
        captured_at=datetime.now(UTC),
        bucket=original.bucket,
        key=key,
    )
    recovered = S3Archive(
        archive.bucket + "-restored",
        endpoint=archive.client.meta.endpoint_url,
        access_key="test",
        secret_key="test",
    )
    recovered.initialize()
    physical = recovered.replicate(archive, original)
    assert physical.bucket != original.bucket and physical.version_id != original.version_id
    map_path = tmp_path / "restore-map.json"
    map_path.write_text(
        json.dumps(
            {
                S3Archive.identity(original): physical.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    restored = archive_from_settings(
        Settings(
            s3_bucket=recovered.bucket,
            s3_endpoint_url=archive.client.meta.endpoint_url,
            s3_access_key="test",
            s3_secret_key="test",
            s3_restore_map=map_path,
        )
    )
    with patch.object(restored.client, "get_object", wraps=restored.client.get_object) as get:
        async with sessions() as session:
            result = await resolve_feed(session, restored, "test-us04", date.today(), tmp_path)
        assert result is not None and result.read_bytes() == path.read_bytes()
        assert get.call_args.kwargs["Bucket"] == recovered.bucket
        assert get.call_args.kwargs["VersionId"] == physical.version_id
    # Corrupção dos bytes no destino não pode ser aceita apenas pelo mapa/metadados.
    changed = restored.client.put_object(Bucket=restored.bucket, Key=physical.key, Body=b"bad zip")
    restored.relocations[S3Archive.identity(original)] = physical.model_copy(
        update={"version_id": changed["VersionId"]}
    )
    bad_output = tmp_path / "corrupt"
    bad_output.mkdir()
    async with sessions() as session:
        with pytest.raises(ValueError, match="hash armazenado"):
            await resolve_feed(session, restored, "test-us04", date.today(), bad_output)


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "other_key",
        "other_source_bucket",
        "target_bucket",
        "sha256",
        "stored_sha256",
        "size",
        "encoding",
    ],
)
async def test_gtfs_catalog_refuses_absent_or_invalid_restore_map(
    invalid: str, tmp_path: Path
) -> None:
    logical = ObjectRef(
        bucket="original",
        key="gtfs/test/feed.zip",
        version_id="original-version",
        sha256="a" * 64,
        stored_sha256="a" * 64,
        size=4,
        stored_size=4,
    )
    physical = logical.model_copy(update={"bucket": "restored", "version_id": "restored-version"})
    identity = logical
    if invalid == "other_key":
        identity = logical.model_copy(update={"key": "gtfs/other/feed.zip"})
    elif invalid == "other_source_bucket":
        identity = logical.model_copy(update={"bucket": "unrelated"})
    elif invalid == "target_bucket":
        physical = physical.model_copy(update={"bucket": "unexpected"})
    elif invalid in {"sha256", "stored_sha256"}:
        physical = physical.model_copy(update={invalid: "b" * 64})
    elif invalid == "size":
        physical = physical.model_copy(update={"size": 5})
    elif invalid == "encoding":
        physical = physical.model_copy(update={"encoding": "gzip"})
    archive = Mock(spec=S3Archive)
    archive.bucket = "restored"
    archive.relocations = {} if invalid == "missing" else {S3Archive.identity(identity): physical}
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = logical.sha256
    session.get.return_value = GtfsVersion(
        sha256=logical.sha256,
        size=logical.size,
        bucket=logical.bucket,
        object_key=logical.key,
    )
    with pytest.raises(ValueError):
        await resolve_feed(session, archive, "test-us04", date.today(), tmp_path)
    archive.reference.assert_not_called()
    archive.download.assert_not_called()
