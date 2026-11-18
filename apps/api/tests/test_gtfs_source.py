import io
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest
from api.gtfs.source import GtfsError, download, inspect_feed


def feed_bytes(*, version: str = "one", calendar_only: bool = False) -> bytes:
    tables = {
        "agency.txt": "agency_name,agency_url,agency_timezone\nTeste,https://example.org,America/Sao_Paulo\n",
        "routes.txt": "route_id,route_type\n1,3\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n1,Teste,-23.5,-46.6\n",
        "trips.txt": "route_id,service_id,trip_id\n1,1,1\n",
        "stop_times.txt": "trip_id,stop_id,stop_sequence\n1,1,1\n",
        "calendar_dates.txt": "service_id,date,exception_type\n1,20261118,1\n1,20261119,1\n",
    }
    if not calendar_only:
        tables["feed_info.txt"] = (
            "feed_start_date,feed_end_date,feed_version\n20261101,20261130," + version + "\n"
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in tables.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), body)
    return output.getvalue()


def test_metadata_and_calendar_fallback(tmp_path: Path) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed_bytes())
    metadata = inspect_feed(path)
    assert metadata.starts_on == date(2026, 11, 1)
    assert metadata.ends_on == date(2026, 11, 30)
    assert metadata.coverage_basis == "feed_info"
    assert metadata.publisher_version == "one"
    path.write_bytes(feed_bytes(calendar_only=True))
    fallback = inspect_feed(path)
    assert fallback.starts_on == date(2026, 11, 18)
    assert fallback.ends_on == date(2026, 11, 19)
    assert fallback.coverage_basis == "calendar_extent"
    assert fallback.sha256 != metadata.sha256


def test_rejects_html_incomplete_and_oversized_archives(tmp_path: Path) -> None:
    path = tmp_path / "feed.zip"
    path.write_text("<html>login</html>")
    with pytest.raises(GtfsError, match="invalid_gtfs"):
        inspect_feed(path)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agency.txt", "agency_name\nTeste\n")
    with pytest.raises(GtfsError):
        inspect_feed(path)
    path.write_bytes(feed_bytes())
    with pytest.raises(GtfsError, match="expanded_feed_too_large"):
        inspect_feed(path, max_expanded_bytes=1)


async def test_download_retries_and_preserves_exact_bytes(tmp_path: Path) -> None:
    calls = 0
    body = feed_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, content=body)

    path = tmp_path / "feed.zip"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await download(client, "https://example.org/feed.zip", path)
    assert calls == 2
    assert path.read_bytes() == body


async def test_download_limit_and_errors_hide_credentials(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"1234"))
    ) as client:
        with pytest.raises(GtfsError, match="download_too_large"):
            await download(client, "https://example.org/?token=secret", tmp_path / "x", max_bytes=2)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403))
    ) as client:
        with pytest.raises(GtfsError) as error:
            await download(client, "https://example.org/?token=secret", tmp_path / "x")
    assert str(error.value) == "source_rejected"
