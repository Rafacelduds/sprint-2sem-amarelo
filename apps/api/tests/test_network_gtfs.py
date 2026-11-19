import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from api.config import get_settings
from api.live import Line, Snapshot
from api.main import app
from api.network_gtfs import (
    FeedProvider,
    FeedReference,
    load_feed,
    normalize_destination,
    prepare_feed,
)
from botocore.response import StreamingBody


def make_feed(
    path: Path,
    *,
    ambiguous: bool = False,
    invalid_shape: bool = False,
    missing_shapes: bool = False,
) -> bytes:
    trips = (
        "route_id,trip_id,direction_id,trip_headsign,shape_id\n"
        "R,one,1,Metrô Vl. Madalena,there\n"
        "R,two,0,Pq. Edu Chaves,back\n"
        "OTHER,three,0,Outro destino,there\n"
    )
    if ambiguous:
        trips += "R,conflict,0,Metro Vila Madalena,back\n"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "routes.txt",
            "route_id,route_short_name,route_type,route_color\n"
            "R,701A-10,3,002F6C\nOTHER,8000-10,3,ABCDEF\nMETRO,L1,1,002F6C\n",
        )
        z.writestr("trips.txt", trips)
        if not missing_shapes:
            lon = "200" if invalid_shape else "-46.63"
            z.writestr(
                "shapes.txt",
                "shape_id,shape_pt_sequence,shape_pt_lat,shape_pt_lon\n"
                f"there,2,-23.56,{lon}\nthere,1,-23.55,-46.64\n"
                "back,1,-23.56,-46.63\nback,2,-23.55,-46.64\n",
            )
    return path.read_bytes()


def test_headsign_matching_does_not_assume_inverse_direction_ids(tmp_path: Path):
    path = tmp_path / "gtfs.zip"
    make_feed(path)
    feed = prepare_feed(path, tmp_path / "shape.sqlite")
    first = feed.match("701A-10", "METRÔ VL. MADALENA")
    second = feed.match("701A-10", "PQ. EDU CHAVES")
    assert first and second
    assert first.direction == "1"  # Deliberately not the real provider's current numbering.
    assert second.direction == "0"
    assert first.shapes == ("there",)
    assert feed.geometry(first.shapes) == [[(-46.64, -23.55), (-46.63, -23.56)]]
    assert normalize_destination("Term. Jd. Britânia") == "terminal jardim britania"
    assert feed.match("701A", "METRO VILA MADALENA") is None
    assert feed.match("L1", "Destinação") is None  # Only bus route_type=3.


@pytest.mark.parametrize("ambiguous", [False, True])
def test_unknown_or_ambiguous_headsign_never_produces_geometry(tmp_path: Path, ambiguous: bool):
    path = tmp_path / "gtfs.zip"
    make_feed(path, ambiguous=ambiguous)
    feed = prepare_feed(path, tmp_path / "shape.sqlite")
    match = feed.match("701A-10", "METRO VILA MADALENA" if ambiguous else "Unknown")
    assert match and match.status == ("ambiguous" if ambiguous else "unmatched")
    assert match.shapes == ()
    assert match.route.color == "#002F6C"  # Color comes from the exact route, independently.


@pytest.mark.parametrize("missing_shapes", [False, True])
def test_bad_or_missing_geometry_keeps_color_without_fabricating_route(
    tmp_path: Path,
    missing_shapes: bool,
):
    path = tmp_path / "gtfs.zip"
    make_feed(path, invalid_shape=True, missing_shapes=missing_shapes)
    feed = prepare_feed(path, tmp_path / "shape.sqlite")
    match = feed.match("701A-10", "Metro Vila Madalena")
    assert match and match.route.color == "#002F6C"
    assert feed.geometry(match.shapes) == []


def test_archive_copy_hash_and_cache_are_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = make_feed(tmp_path / "source.zip")
    version = hashlib.sha256(data).hexdigest()
    ref = FeedReference(
        version,
        datetime.now(UTC),
        "https://official.example/gtfs",
        "bucket",
        "gtfs/source.zip",
        len(data),
    )
    client = MagicMock()
    client.get_object.return_value = {"Body": StreamingBody(io.BytesIO(data), len(data))}
    monkeypatch.setattr("api.network_gtfs.archive_client", lambda: client)
    monkeypatch.setattr(get_settings(), "network_cache_dir", tmp_path / "cache")
    feed = load_feed(ref)
    assert feed.match("701A-10", "Metro Vila Madalena")
    load_feed(ref)
    client.get_object.assert_called_once_with(Bucket="bucket", Key="gtfs/source.zip")
    cached = tmp_path / "cache" / version / "feed.zip"
    corrupted = bytearray(data)
    corrupted[-1] ^= 1
    cached.write_bytes(corrupted)
    with pytest.raises(ValueError, match="cache_hash_mismatch"):
        load_feed(ref)
    assert not cached.exists()
    # The next attempt recovers from the immutable source without manual intervention.
    client.get_object.return_value = {"Body": StreamingBody(io.BytesIO(data), len(data))}
    recovered = load_feed(ref)
    assert recovered.match("701A-10", "Metro Vila Madalena")
    assert cached.read_bytes() == data
    assert client.get_object.call_count == 2
    assert (tmp_path / "source.zip").read_bytes() == data


@pytest.mark.asyncio
async def test_provider_version_change_and_failure_do_not_mix_feeds(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = FeedProvider()
    first = FeedReference("a" * 64, datetime.now(UTC), "source", "bucket", "key", 1)
    second = FeedReference("b" * 64, datetime.now(UTC), "source", "bucket", "key", 1)
    latest = AsyncMock(side_effect=[first, second, RuntimeError("private database URL")])
    loader = MagicMock(side_effect=["feed-a", "feed-b"])
    monkeypatch.setattr("api.network_gtfs.latest_reference", latest)
    monkeypatch.setattr("api.network_gtfs.load_feed", loader)
    assert await provider.get() == (first, "feed-a")
    assert await provider.get() == (first, "feed-a")
    assert loader.call_count == 1
    provider.next_check = 0
    assert await provider.get() == (second, "feed-b")
    provider.next_check = 0
    assert await provider.get() is None


@pytest.mark.asyncio
async def test_automatic_catalog_colors_and_lazy_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "gtfs.zip"
    make_feed(path)
    feed = prepare_feed(path, tmp_path / "shape.sqlite")
    ref = FeedReference(
        "a" * 64,
        datetime.now(UTC),
        "https://official.example/gtfs",
        "bucket",
        "key",
        path.stat().st_size,
    )
    monkeypatch.setattr(get_settings(), "network_catalog_path", None)
    monkeypatch.setattr("api.network.feed_provider.get", AsyncMock(return_value=(ref, feed)))
    snap = Snapshot(
        collected_at=datetime.now(UTC),
        served_at=datetime.now(UTC),
        vehicles=[],
        lines=[
            Line(id=689, label="701A-10", direction=1, destination="Metro Vl. Madalena"),
            Line(id=33457, label="701A-10", direction=2, destination="Pq. Edu Chaves"),
            Line(id=88, label="8000-10", direction=1, destination="Outro destino"),
        ],
    )
    monkeypatch.setattr("api.network.live_positions.get", AsyncMock(return_value=snap))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        catalog = (await c.get("/network/catalog")).json()
        assert catalog["status"] == "ready" and catalog["synthetic"] is False
        assert catalog["lines"][0]["color"] == "#002F6C"
        assert catalog["lines"][0]["area_id"] == 2
        assert catalog["lines"][1]["direction_id"] == "0"
        assert catalog["lines"][2]["color"] == "#ABCDEF"
        assert catalog["lines"][2]["area_id"] is None  # Never infer area from the line number.
        route = await c.get("/network/routes/689", params={"version": "a" * 64})
        assert route.status_code == 200
        assert route.json()["features"][0]["geometry"]["coordinates"][0][0] == [-46.64, -23.55]
        assert (await c.get("/network/routes/689", params={"version": "b" * 64})).status_code == 404
        assert (await c.get("/network/routes/999")).status_code == 404
