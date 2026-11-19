from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from api.live import LivePositions, live_positions, normalize
from api.main import app
from fastapi import HTTPException


def payload() -> dict[str, object]:
    return {
        "l": [
            {
                "cl": 10,
                "c": "5015-10",
                "sl": 1,
                "lt0": "Terminal",
                "vs": [
                    {"p": 123, "py": -23.55, "px": -46.63, "ta": "2026-11-18T12:00:00Z", "a": True}
                ],
            }
        ]
    }


def test_normalization_preserves_distinct_gps_and_collection_times() -> None:
    now = datetime.now(UTC)
    result = normalize(payload(), now)
    assert result.collected_at == now
    assert result.vehicles[0].gps_at != now
    assert result.vehicles[0].id == "123"
    assert result.lines[0].label == "5015-10"


def test_discards_invalid_coordinates_and_unknown_line_structure() -> None:
    result = normalize(
        {
            "l": [
                {"invalid": True},
                {
                    "cl": 1,
                    "c": "X",
                    "sl": 1,
                    "vs": [
                        {"p": 1, "py": 100, "px": 0},
                        {"p": 2, "py": 0, "px": 0},
                        {"p": 3, "py": -23, "px": -46, "ta": "2026-11-18T12:00:00"},
                    ],
                },
            ]
        },
        datetime.now(UTC),
    )
    assert result.vehicles == []
    assert result.discarded == 4


@pytest.mark.asyncio
async def test_cache_coalesces_and_filters_without_collecting_again() -> None:
    service = LivePositions()
    fetch = AsyncMock(return_value=normalize(payload(), datetime.now(UTC)))
    service.fetch = fetch
    first = await service.get()
    second = await service.get()
    assert first.collected_at == second.collected_at
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_failure_keeps_original_timestamp_and_marks_expired() -> None:
    service = LivePositions()
    old = datetime.now(UTC) - timedelta(seconds=61)
    service.snapshot = normalize(payload(), old)
    service.fetch = AsyncMock(side_effect=httpx.ConnectError("secret upstream detail"))
    result = await service.get()
    assert result.stale
    assert result.collected_at == old


@pytest.mark.asyncio
async def test_first_failure_is_safe_and_backed_off() -> None:
    service = LivePositions()
    fetch = AsyncMock(side_effect=ValueError("secret token must not leak"))
    service.fetch = fetch
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await service.get()
        assert error.value.status_code == 503
        assert "secret" not in error.value.detail
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_endpoint_filter_and_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        live_positions,
        "get",
        AsyncMock(
            return_value=normalize(payload(), datetime.now(UTC)),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        found = await client.get("/vehicles/positions?line_id=10")
        empty = await client.get("/vehicles/positions?line_id=99")
        invalid = await client.get("/vehicles/positions?line_id=abc")
    assert found.status_code == 200
    assert found.headers["cache-control"] == "no-store"
    assert len(found.json()["vehicles"]) == 1
    assert empty.json()["vehicles"] == []
    assert len(empty.json()["lines"]) == 1
    assert invalid.status_code == 422


def test_destination_uses_directional_headsign_not_always_lt0() -> None:
    raw: dict[str, object] = {
        "l": [
            {
                "cl": 1,
                "c": "701A-10",
                "sl": 1,
                "lt0": "Metro",
                "lt1": "Parque",
                "vs": [{"p": 1, "py": -23, "px": -46}],
            },
            {
                "cl": 2,
                "c": "701A-10",
                "sl": 2,
                "lt0": "Metro",
                "lt1": "Parque",
                "vs": [{"p": 2, "py": -23, "px": -46}],
            },
            {"cl": 3, "c": "701A-10", "sl": 2, "lt0": "Metro", "vs": []},
        ]
    }
    result = normalize(raw, datetime.now(UTC))
    assert [line.destination for line in result.lines] == ["Metro", "Parque", ""]
    assert [bus.destination for bus in result.vehicles] == ["Metro", "Parque"]
