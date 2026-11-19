import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from api.config import get_settings
from api.main import app
from api.network import NetworkExport, read_export
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures/network.synthetic.json"


def test_explicit_mapping_not_direction_assumption() -> None:
    network = NetworkExport.model_validate_json(FIXTURE.read_bytes())
    assert network.synthetic
    assert network.features[0].properties.direction == 1
    assert network.features[0].properties.direction_id == "1"
    assert network.features[1].properties.direction_id == "0"


@pytest.mark.parametrize("change", ["duplicate", "coords", "area_source", "version"])
def test_rejects_ambiguous_or_unproven_catalog(change: str) -> None:
    data: Any = json.loads(FIXTURE.read_text())
    if change == "duplicate":
        data["features"].append(data["features"][0])
    elif change == "coords":
        data["features"][0]["geometry"]["coordinates"] = [[[200, -23], [-46, -24]]]
    elif change == "area_source":
        data["features"][0]["properties"]["area_source"] = None
    else:
        data["version"] = "missing-hash"
    with pytest.raises(ValidationError):
        NetworkExport.model_validate(data)


@pytest.mark.asyncio
async def test_catalog_geometry_and_version_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "network.json"
    path.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(get_settings(), "network_catalog_path", str(path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        catalog = (await c.get("/network/catalog")).json()
        assert catalog["status"] == "ready"
        assert catalog["lines"][0]["color"] == "#002F6C"
        assert len(catalog["areas"]) == 9
        route = await c.get("/network/routes/1", params={"version": "a" * 64})
        assert route.status_code == 200
        assert route.json()["features"][0]["geometry"]["coordinates"][0][0] == [-46.65, -23.54]
        assert (await c.get("/network/routes/999")).status_code == 404
        data = json.loads(path.read_text())
        data["version"] = "b" * 64
        path.write_text(json.dumps(data))
        assert (await c.get("/network/catalog")).json()["version"] == "b" * 64
        assert (await c.get("/network/routes/1", params={"version": "a" * 64})).status_code == 404
    read_export.cache_clear()


@pytest.mark.asyncio
async def test_unavailable_catalog_keeps_palette_and_no_fake_routes(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(get_settings(), "network_catalog_path", "/nonexistent/catalog.json")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        catalog = (await c.get("/network/catalog")).json()
        assert catalog["status"] == "unavailable"
        assert catalog["lines"] == []
        assert catalog["synthetic"] is False
        assert len(catalog["areas"]) == 9
        assert (await c.get("/network/routes/1")).status_code == 404
