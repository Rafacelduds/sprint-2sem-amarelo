import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import duckdb
import httpx
import pytest
from api.gtfs.catalog import Catalog
from api.gtfs.source import inspect_feed
from api.schedules.catalog import resolve_feed
from api.schedules.gtfs import generate
from api.schedules.models import OfficialLine, official_departures, seconds
from api.schedules.runner import ArchiveFailure, OfficialSource, SourceUnavailable, run
from api.storage.s3 import S3Archive
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_storage import archive as archive  # noqa: F401


def official(line: str = "1012-10") -> dict[str, object]:
    return {
        "codigoLinha": line,
        "partidasIda": [
            {
                "tipoDia": 0,
                "faixaHoraria": 23,
                "totalPartidas": 1,
                "horariosProgramados": [{"horario": "23:30"}],
            },
            {
                "tipoDia": 0,
                "faixaHoraria": 0,
                "totalPartidas": 1,
                "horariosProgramados": [{"horario": "00:30"}],
            },
        ],
        "partidasVolta": [],
    }


def feed(path: Path, *, exact: str = "0", overlap: bool = False, daily: bool = False) -> Path:
    tables = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Test,https://example.org,America/Sao_Paulo\n"
        ),
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\na,A,-23.5,-46.5\n",
        "routes.txt": "route_id,route_short_name,route_type\nr,1012-10,3\nr2,1012-21,3\n",
        "trips.txt": "route_id,service_id,trip_id,direction_id\nr,U,t,0\nr2,U,fixed,1\n",
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,"
            "saturday,sunday,start_date,end_date\n"
            "U,1,1,1,1,1,0,0,20200101,20991231\n"
        ),
        "calendar_dates.txt": "service_id,date,exception_type\nU,20260523,1\nU,20260525,2\n",
        "stop_times.txt": (
            "trip_id,stop_id,stop_sequence,departure_time\n"
            "t,a,2,26:00:00\nt,a,1,25:00:00\nfixed,a,1,25:00:00\n"
        ),
        "frequencies.txt": "trip_id,start_time,end_time,headway_secs,exact_times\n"
        f"t,25:00:00,26:00:00,1200,{exact}\n",
    }
    if overlap:
        tables["frequencies.txt"] += f"t,25:30:00,26:30:00,1200,{exact}\n"
    if daily:
        tables["calendar.txt"] = tables["calendar.txt"].replace("1,1,1,1,1,0,0", "1,1,1,1,1,1,1")
        tables["calendar_dates.txt"] = "service_id,date,exception_type\n"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as z:
        for name, body in tables.items():
            z.writestr(name, body)
    path.write_bytes(buffer.getvalue())
    return path


def test_official_order_and_midnight_are_preserved() -> None:
    departures, expected = official_departures(
        OfficialLine.model_validate(official()), "1012-10", date(2026, 5, 18), "U", "a" * 64
    )
    assert [row.departure_seconds for row in departures] == [84600, 1800]
    assert expected == {"0": 2, "1": 0}
    assert all(row.direction_system == "sptrans_itinerarios" for row in departures)
    with pytest.raises(ValueError, match="sem programação"):
        official_departures(
            OfficialLine.model_validate(official()), "1012-10", date(2026, 5, 23), "S", "a" * 64
        )
    with pytest.raises(ValueError, match="diverge"):
        official_departures(
            OfficialLine.model_validate(official()), "OTHER", date(2026, 5, 18), "U", "a" * 64
        )


def test_official_discrepancy_preserves_list_and_declared_total() -> None:
    payload = json.dumps(official()).replace('"totalPartidas": 1', '"totalPartidas": 4')
    departures, expected = official_departures(
        OfficialLine.model_validate_json(payload), "1012-10", date(2026, 5, 18), "U", "a" * 64
    )
    assert len(departures) == 2 and expected == {"0": 8, "1": 0}


@pytest.mark.parametrize("value", ["04:99", "-1:00", "bad", "24:00:70"])
def test_invalid_time_is_not_zero(value: str) -> None:
    with pytest.raises(ValueError):
        seconds(value)


@pytest.mark.parametrize("exact,kind", [("0", "gtfs_frequency_estimate"), ("1", "gtfs_exact")])
def test_gtfs_calendar_exceptions_frequencies_and_fixed(
    tmp_path: Path, exact: str, kind: str
) -> None:
    path = feed(tmp_path / "feed.zip", exact=exact)
    lines = {"1012-10", "1012-21"}
    for day in (date(2026, 5, 18), date(2026, 5, 23)):
        departures = generate(path, day, lines, "b" * 64)
        frequency = [row for row in departures if row.line == "1012-10"]
        assert [row.departure_seconds for row in frequency] == [90000, 91200, 92400]
        assert all(row.kind == kind for row in frequency)
        fixed = [row for row in departures if row.line == "1012-21"]
        assert len(fixed) == 1 and fixed[0].kind == "gtfs_fixed"
        assert fixed[0].direction == "1" and fixed[0].direction_system == "gtfs"
    assert generate(path, date(2026, 5, 24), lines, "b" * 64) == []
    assert generate(path, date(2026, 5, 25), lines, "b" * 64) == []


def test_overlapping_frequencies_fail(tmp_path: Path) -> None:
    path = feed(tmp_path / "feed.zip", overlap=True)
    with pytest.raises(ValueError, match="sobrepostas"):
        generate(path, date(2026, 5, 18), {"1012-10"}, "b" * 64)


@pytest.fixture
def server() -> Iterator[tuple[str, list[str]]]:
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            status = 200
            if self.path == "/RetornarLinhasTeste":
                data: object = [
                    {"codigo": "1012-10", "CdPjOID": 1},
                    {"codigo": "1012-21", "CdPjOID": 2},
                ]
            elif self.path == "/BuscarDetalheLinhaTeste":
                assert json.loads(body)["codPlanejamento"] in {1, 2}
                if json.loads(body)["codPlanejamento"] == 2:
                    status, data = 503, {"error": "synthetic unavailable"}
                elif calls.count(self.path) == 1:
                    status, data = 503, {"error": "synthetic transient"}
                else:
                    data = official()
            else:
                status, data = 501, {"error": "unmodelled"}
            encoded = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/", calls
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def test_http_retry_official_priority_and_s3_immutable_restart(
    server: tuple[str, list[str]], archive: S3Archive, tmp_path: Path
) -> None:
    url, calls = server
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    gtfs = feed(tmp_path / "feed.zip", daily=True)
    with httpx.Client(base_url=url, timeout=2, trust_env=False) as client:
        source = OfficialSource(client, backoff=0)
        first = run(
            source, archive, tmp_path / "runs", day=day, day_type="U", gtfs_file=gtfs, interval=0
        )
        second = run(
            source, archive, tmp_path / "runs", day=day, day_type="U", gtfs_file=gtfs, interval=0
        )
    assert first["complete"] and second["complete"]
    assert first["official_lines_checked"] == 1
    assert first["lines"][0]["status"] == "official"
    assert first["lines"][1]["status"] == "gtfs"
    assert calls.count("/BuscarDetalheLinhaTeste") == 9
    assert first["output"]["sha256"] == second["output"]["sha256"]
    assert first["run_id"] != second["run_id"]
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT line, kind, count(*) FROM read_parquet(?) GROUP BY ALL ORDER BY line",
            [str(tmp_path / "runs" / first["run_id"] / "departures.parquet")],
        ).fetchall()
    assert rows == [("1012-10", "official", 2), ("1012-21", "gtfs_fixed", 1)]
    versions = archive.client.list_object_versions(Bucket=archive.bucket)
    keys = [row["Key"] for row in versions.get("Versions", [])]
    assert len(keys) == len(set(keys))  # Repetição não cria nova versão dos mesmos bytes.


def test_http_failure_does_not_fabricate_zero(server: tuple[str, list[str]]) -> None:
    with httpx.Client(base_url=server[0], timeout=2, trust_env=False) as client:
        with pytest.raises(SourceUnavailable):
            OfficialSource(client, retries=2, backoff=0).fetch(
                "BuscarDetalheLinhaTeste", {"codPlanejamento": 2}
            )


def test_storage_failure_is_not_hidden_by_fallback(
    server: tuple[str, list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = S3Archive(
        "unused", endpoint="http://127.0.0.1:1", access_key="test", secret_key="test"
    )

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("synthetic storage failure")

    monkeypatch.setattr(archive, "put", broken)
    with httpx.Client(base_url=server[0], timeout=2, trust_env=False) as client:
        with pytest.raises(ArchiveFailure):
            run(
                OfficialSource(client),
                archive,
                tmp_path / "out",
                day=datetime.now(ZoneInfo("America/Sao_Paulo")).date(),
                day_type="U",
            )


async def test_us02_catalog_reference_is_verified_and_source_scoped(
    sessions: async_sessionmaker[AsyncSession], archive: S3Archive, tmp_path: Path
) -> None:
    path = feed(tmp_path / "feed.zip", daily=True)
    metadata = inspect_feed(path)
    ref = archive.put(path, f"raw/schedules/gtfs/{metadata.sha256}.zip")
    await Catalog(sessions).record(
        metadata,
        source_id="test-us04",
        source_url="https://example.org/feed.zip",
        captured_at=datetime.now(UTC),
        bucket=archive.bucket,
        key=ref.key,
    )
    async with sessions() as session:
        assert await resolve_feed(session, archive, "other", date.today(), tmp_path) is None
        result = await resolve_feed(session, archive, "test-us04", date.today(), tmp_path)
    assert result is not None and result.read_bytes() == path.read_bytes()


def test_report_warns_about_discrepancy_without_replacing_official(
    archive: S3Archive, tmp_path: Path
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/RetornarLinhasTeste":
            return httpx.Response(200, json=[{"codigo": "1012-10", "CdPjOID": 1}])
        return httpx.Response(
            200, content=json.dumps(official()).replace('"totalPartidas": 1', '"totalPartidas": 4')
        )

    def forbidden_fallback(directory: Path) -> Path | None:
        pytest.fail("programação oficial disponível não deve ser substituída")

    with httpx.Client(base_url="https://example.org", transport=httpx.MockTransport(response)) as c:
        report = run(
            OfficialSource(c),
            archive,
            tmp_path,
            day=datetime.now(ZoneInfo("America/Sao_Paulo")).date(),
            day_type="U",
            gtfs_loader=forbidden_fallback,
            interval=0,
        )
    assert report["complete"] and report["has_discrepancies"]
    assert not report["acceptance_30_lines"]
    assert report["official_lines_checked"] == 1 and report["official_lines_concordant"] == 0
    assert report["lines"][0]["written"] == {"0": 2}
