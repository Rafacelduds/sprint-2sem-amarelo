from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from api.gtfs.catalog import Catalog
from api.gtfs.runner import GtfsCollector, GtfsSettings
from api.gtfs.source import GtfsError
from api.gtfs.storage import Archive
from pydantic import SecretStr, ValidationError
from test_gtfs_source import feed_bytes


def settings(**overrides: object) -> GtfsSettings:
    return GtfsSettings.model_validate(
        {
            "gtfs_source_url": "https://example.org/feed?token=secret",
            **overrides,
        }
    )


async def test_invalid_download_or_failed_archive_never_publishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    archive = Mock(spec=Archive)
    archive.preserve.side_effect = GtfsError("archive_write_failed")
    catalog = AsyncMock(spec=Catalog)
    for body in (b"<html>login</html>", feed_bytes()):

        def handler(request: httpx.Request, content: bytes = body) -> httpx.Response:
            return httpx.Response(200, content=content)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            collector = GtfsCollector(client, archive, catalog, settings())
            assert not await collector.run(once=True)
    catalog.record.assert_not_called()
    assert "secret" not in caplog.text


async def test_failed_cycle_retries_soon_and_cancellation_stops() -> None:
    async with httpx.AsyncClient() as client:
        collector = GtfsCollector(client, Mock(spec=Archive), AsyncMock(spec=Catalog), settings())
        with (
            patch.object(collector, "cycle", new=AsyncMock(return_value=False)) as cycle,
            patch(
                "api.gtfs.runner.asyncio.sleep", new=AsyncMock(side_effect=RuntimeError("stop"))
            ) as sleep,
        ):
            with pytest.raises(RuntimeError, match="stop"):
                await collector.run()
            cycle.assert_awaited_once()
            assert 299 <= sleep.call_args.args[0] <= 300


def test_settings_bounds_and_secret_repr() -> None:
    assert settings().gtfs_interval_seconds == 86400
    assert "secret" not in repr(settings().gtfs_source_url)
    for overrides in (
        {"gtfs_attempts": 0},
        {"gtfs_source_id": "../bad"},
        {"gtfs_interval_seconds": 0},
    ):
        with pytest.raises(ValidationError):
            settings(**overrides)


async def test_temporary_file_removed_and_catalog_errors_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    paths: list[Path] = []

    def preserve(path: Path, *_: object) -> str:
        paths.append(path)
        assert path.read_bytes() == feed_bytes()
        return "gtfs/test.zip"

    archive = Mock(spec=Archive)
    archive.preserve.side_effect = preserve
    catalog = AsyncMock(spec=Catalog)
    catalog.record.side_effect = RuntimeError("password=secret")
    configured = settings()
    configured.gtfs_source_url = SecretStr("https://example.org/feed?token=secret")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=feed_bytes())),
    ) as client:
        assert not await GtfsCollector(client, archive, catalog, configured).cycle()
    assert len(paths) == 1 and not paths[0].exists()
    assert "secret" not in caplog.text


async def test_local_import_without_url_preserves_original_and_records_safe_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "feed recebido.zip"
    body = feed_bytes()
    source.write_bytes(body)
    archive = Mock(spec=Archive)

    def preserve(path: Path, *_: object) -> str:
        assert path != source and path.read_bytes() == body
        return "gtfs/test.zip"

    archive.preserve.side_effect = preserve
    catalog = AsyncMock(spec=Catalog)

    def no_network(request: httpx.Request) -> httpx.Response:
        pytest.fail("Importação local não deve fazer requisições HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        collector = GtfsCollector(client, archive, catalog, settings(gtfs_source_url=""))
        assert await collector.import_file(source)
    assert source.read_bytes() == body
    catalog.record.assert_awaited_once()
    assert catalog.record.call_args.kwargs["source_url"] == "file://imported/feed%20recebido.zip"


@pytest.mark.parametrize("missing", [False, True])
async def test_local_import_limits_and_missing_file_never_publish(
    tmp_path: Path,
    missing: bool,
) -> None:
    source = tmp_path / "feed.zip"
    if not missing:
        source.write_bytes(feed_bytes())
    archive, catalog = Mock(spec=Archive), AsyncMock(spec=Catalog)
    async with httpx.AsyncClient() as client:
        collector = GtfsCollector(client, archive, catalog, settings(gtfs_max_bytes=1))
        assert not await collector.import_file(source)
    archive.preserve.assert_not_called()
    catalog.record.assert_not_called()
    assert source.exists() is not missing
