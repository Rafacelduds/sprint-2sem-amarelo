import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from api.main import create_app
from api.schedules.models import Departure
from api.schedules.routes import get_archive
from api.schedules.runner import write_parquet
from api.storage.s3 import S3Archive, digest
from test_storage import archive as archive  # noqa: F401

DAY = date(2026, 11, 19)


def seed(archive: S3Archive, path: Path, *, status: str = "official") -> str:
    """Artefatos inteiramente sintéticos; testa o leitor, sem chamar fonte externa."""
    run_id = str(uuid4())
    raw = path / f"{run_id}.json"
    raw.write_text('{"synthetic":true}', encoding="utf-8")
    source = archive.put(raw, f"raw/schedules/sptrans/{run_id}.json")
    items = []
    if status == "official":
        items = [
            Departure(
                "1012-10",
                "0",
                "sptrans_itinerarios",
                DAY,
                value,
                "official",
                source.sha256,
                source_order=index,
            )
            for index, value in enumerate([84600, 1800, 1800])
        ]
    elif status == "gtfs":
        items = [
            Departure("1012-10", "", "gtfs", DAY, 90000, "gtfs_frequency_estimate", source.sha256)
        ]
    parquet = path / f"{run_id}.parquet"
    write_parquet(parquet, items)
    sha, _ = digest(parquet)
    output = archive.put(parquet, f"derived/schedules/us04-v1/{sha}.parquet")
    line: dict[str, object] = {
        "line": "1012-10",
        "status": status,
        "reason": "secret-token http://private.invalid",
    }
    if status != "unavailable":
        line.update(source_sha256=source.sha256, written=len(items))
    if status == "official":
        line.update(expected={"0": 4, "1": 0}, written={"0": 3}, declared_counts_match=False)
    manifest = {
        "run_id": run_id,
        "rule_version": "us04-v1",
        "code_version": "a" * 40,
        "started_at": "2026-11-19T12:00:00Z",
        "finished_at": "2026-11-19T12:01:00Z",
        "service_date": DAY.isoformat(),
        "day_type": "U",
        "timezone": "America/Sao_Paulo",
        "source_url": "http://private.invalid?token=secret",
        "validity": "capture_reference_only_not_official_historical_validity",
        "operational_day_cutoff": None,
        "inputs": [source.model_dump(mode="json")],
        "captures": [
            {
                "captured_at": datetime(2026, 11, 19, 12, tzinfo=UTC).isoformat(),
                "reference": source.model_dump(mode="json"),
            }
        ],
        "output": output.model_dump(mode="json"),
        "lines": [line],
        "official_lines_checked": int(status == "official"),
        "official_lines_concordant": 0,
        "has_discrepancies": status == "official",
        "acceptance_30_lines": False,
        "complete": status != "unavailable",
    }
    raw.write_text(json.dumps(manifest), encoding="utf-8")
    archive.put(raw, f"manifests/schedules/{run_id}.json")
    return run_id


def client_for(archive: S3Archive) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_archive] = lambda: archive
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_public_catalog_and_paging_preserve_midnight_duplicates_and_provenance(
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    run_id = seed(archive, tmp_path)
    async with client_for(archive) as client:
        empty = await client.get("/schedules", params={"day": "2026-11-18"})
        assert empty.status_code == 200 and empty.json()["runs"] == []
        catalog = await client.get("/schedules", params={"day": DAY.isoformat()})
        assert catalog.status_code == 200
        assert catalog.headers["cache-control"] == "no-store"
        run = catalog.json()["runs"][0]
        assert run["run_id"] == run_id and run["has_discrepancies"]
        assert run["operational_day_cutoff"] is None
        assert all(
            secret not in catalog.text for secret in ["private.invalid", "secret", "bucket", "raw/"]
        )
        response = await client.get(
            f"/schedules/{run_id}/departures", params={"line": "1012-10", "limit": 2}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert [row["time"] for row in body["items"]] == ["23:30:00", "00:30:00"]
        assert body["line"]["declared_counts_match"] is False
        assert body["direction_totals"] == [
            {"direction": "0", "written": 3, "declared": 4},
            {"direction": "1", "written": 0, "declared": 0},
        ]
        second = await client.get(
            f"/schedules/{run_id}/departures", params={"line": "1012-10", "offset": 2}
        )
        assert [row["source_order"] for row in second.json()["items"]] == [2]
        assert second.json()["items"][0]["time"] == "00:30:00"
        other = await client.get(
            f"/schedules/{run_id}/departures", params={"line": "1012-10", "direction": "1"}
        )
        assert other.json()["total"] == 0 and other.json()["line"]["status"] == "official"


@pytest.mark.parametrize("status", ["gtfs", "gtfs_no_departures", "unavailable"])
async def test_gtfs_estimates_unknown_direction_and_source_absence_are_distinct(
    archive: S3Archive,
    tmp_path: Path,
    status: str,
) -> None:
    run_id = seed(archive, tmp_path, status=status)
    async with client_for(archive) as client:
        response = await client.get(f"/schedules/{run_id}/departures", params={"line": "1012-10"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["line"]["status"] == status
        assert "private.invalid" not in response.text
        if status == "gtfs":
            assert body["items"][0]["time"] == "25:00:00"
            assert body["items"][0]["kind"] == "gtfs_frequency_estimate"
            unknown = await client.get(
                f"/schedules/{run_id}/departures",
                params={"line": "1012-10", "direction": "unknown"},
            )
            assert unknown.json()["total"] == 1
        else:
            assert body["items"] == []


async def test_invalid_filters_and_missing_run_or_line(
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    run_id = seed(archive, tmp_path)
    async with client_for(archive) as client:
        assert (await client.get("/schedules", params={"day": "not-a-date"})).status_code == 422
        assert (
            await client.get(f"/schedules/{uuid4()}/departures", params={"line": "1012-10"})
        ).status_code == 404
        for params in [
            {"line": "x' OR 1=1"},
            {"line": "1012-10", "limit": 501},
            {"line": "1012-10", "direction": "8"},
            {"line": "1012-10", "offset": -1},
        ]:
            assert (
                await client.get(f"/schedules/{run_id}/departures", params=params)
            ).status_code == 422
        assert (
            await client.get(f"/schedules/{run_id}/departures", params={"line": "other"})
        ).status_code == 404


@pytest.mark.parametrize("mode", ["missing", "corrupt", "manifest_corrupt"])
async def test_unavailable_bytes_never_return_old_or_unverified_departures(
    archive: S3Archive,
    tmp_path: Path,
    mode: str,
) -> None:
    run_id = seed(archive, tmp_path)
    key = (
        f"manifests/schedules/{run_id}.json"
        if mode == "manifest_corrupt"
        else next(archive.objects("derived/schedules/")).key
    )
    ref = archive.reference(key)
    if mode == "missing":
        archive.client.delete_object(Bucket=archive.bucket, Key=key, VersionId=ref.version_id)
    else:
        damaged = archive.client.put_object(
            Bucket=archive.bucket,
            Key=key,
            Body=b"corrupt",
            Metadata={
                "original-sha256": ref.sha256,
                "stored-sha256": ref.stored_sha256,
                "original-size": str(ref.size),
            },
        )
        if mode == "corrupt":
            # Apontar a publicação de teste para bytes realmente divergentes,
            # mantendo o hash esperado. O manifesto em si tem hash válido.
            manifest_key = f"manifests/schedules/{run_id}.json"
            body = archive.client.get_object(Bucket=archive.bucket, Key=manifest_key)["Body"]
            try:
                manifest = json.loads(body.read())
            finally:
                body.close()
            manifest["output"]["version_id"] = damaged["VersionId"]
            path = tmp_path / "damaged-publication.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            sha, size = digest(path)
            archive.client.put_object(
                Bucket=archive.bucket,
                Key=manifest_key,
                Body=path.read_bytes(),
                Metadata={"original-sha256": sha, "stored-sha256": sha, "original-size": str(size)},
            )
    async with client_for(archive) as client:
        result = await client.get(f"/schedules/{run_id}/departures", params={"line": "1012-10"})
        assert result.status_code == 503, result.text
        assert "corrupt" not in result.text and "items" not in result.json()


async def test_storage_configuration_failure_is_public_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.schedules import routes

    def unavailable(*_args: object, **_kwargs: object) -> S3Archive:
        raise RuntimeError("private endpoint and secret token")

    monkeypatch.setattr(routes, "archive_from_settings", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/schedules", params={"day": DAY.isoformat()})
        assert response.status_code == 503
        assert "secret" not in response.text and "private" not in response.text
