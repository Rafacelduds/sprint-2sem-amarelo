"""HTTP local real → coletor → S3 local → PostgreSQL. Fixture GTFS sintética."""

import os
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import boto3
import httpx
import pytest
from api.gtfs.catalog import Catalog
from api.gtfs.models import GtfsCapture, GtfsVersion
from api.gtfs.runner import GtfsCollector, GtfsSettings
from api.gtfs.storage import S3Archive
from botocore.config import Config
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection_postgres import sessions as sessions
from test_gtfs_source import feed_bytes


@pytest.fixture
def http_feed() -> Iterator[tuple[str, list[str]]]:
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(self.path)
            if self.path != "/feed.zip":
                self.send_response(501)
                body = b"unmodelled route"
            elif len(calls) == 1:
                self.send_response(503)
                body = b"temporarily unavailable"
            else:
                self.send_response(200)
                body = feed_bytes()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/feed.zip", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_real_http_s3_postgres_idempotency(
    sessions: async_sessionmaker[AsyncSession],
    http_feed: tuple[str, list[str]],
    tmp_path: Path,
) -> None:
    endpoint = os.getenv("TEST_S3_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("TEST_S3_ENDPOINT_URL não configurada: requer S3 local de testes")
    bucket = "gtfs-test-" + uuid4().hex
    s3 = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
        config=Config(request_checksum_calculation="when_required"),
    )
    s3.create_bucket(Bucket=bucket)
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    try:
        url, calls = http_feed
        settings = GtfsSettings(
            gtfs_source_url=SecretStr(url),
            s3_bucket=bucket,
            s3_endpoint_url=endpoint,
        )
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            collector = GtfsCollector(client, S3Archive(s3, bucket), Catalog(sessions), settings)
            assert await collector.run(once=True)
            assert await collector.run(once=True)
            local = tmp_path / "feed.zip"
            local.write_bytes(feed_bytes())
            assert await collector.import_file(local)
            assert local.read_bytes() == feed_bytes()
        assert calls == ["/feed.zip"] * 3  # 503, tentativa bem-sucedida e nova verificação.
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(GtfsVersion)) == 1
            assert await session.scalar(select(func.count()).select_from(GtfsCapture)) == 3
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(GtfsCapture)
                    .where(GtfsCapture.source_url == "file://imported/feed.zip")
                )
                == 1
            )
            version = await session.scalar(select(GtfsVersion))
            assert version is not None
            response = s3.get_object(Bucket=bucket, Key=version.object_key)
            assert response["Body"].read() == feed_bytes()
            assert response["Metadata"]["sha256"] == version.sha256
        assert len(s3.list_objects_v2(Bucket=bucket).get("Contents", [])) == 1
        assert len(s3.list_object_versions(Bucket=bucket).get("Versions", [])) == 1
    finally:
        for obj in s3.list_object_versions(Bucket=bucket).get("Versions", []):
            key = obj.get("Key")
            version_id = obj.get("VersionId")
            assert key is not None and version_id is not None
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
        s3.delete_bucket(Bucket=bucket)
