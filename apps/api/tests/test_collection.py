import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from api.collection.runner import CollectionSettings, Collector
from api.collection.source import OlhoVivo, Positions, Snapshot, SourceError
from api.collection.store import PostgresStore
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict


class IsolatedSettings(CollectionSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


@pytest.mark.parametrize("interval", [14, 61])
def test_interval_rejects_out_of_bounds(interval: int) -> None:
    with pytest.raises(ValidationError):
        IsolatedSettings(collection_interval_seconds=interval)


@pytest.mark.asyncio
async def test_authentication_cookie_and_garage_queries() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("Autenticar"):
            assert request.method == "POST"
            return httpx.Response(200, json=True, headers={"set-cookie": "session=test; Path=/"})
        assert request.headers["cookie"] == "session=test"
        if request.url.path.endswith("Empresa"):
            return httpx.Response(200, json=[{"e": [{"e": [{"c": 5}, {"c": 7}]}]}])
        if request.url.path.endswith("Garagem"):
            assert request.url.params["codigoEmpresa"] == "5"
        return httpx.Response(200, json={"l": [{"vs": [{"p": 123}]}]})

    async with httpx.AsyncClient(
        base_url="https://example.test/v2.1/", transport=httpx.MockTransport(handler)
    ) as client:
        source = OlhoVivo(client, "private-token")
        assert await source.company_codes() == [5, 7]
        snapshot = await source.snapshot(5)
        assert snapshot.positions.lines[0].vs[0].ta is None
        assert snapshot.company == 5
        assert snapshot.collected_at.tzinfo is UTC
        assert snapshot.body == b'{"l":[{"vs":[{"p":123}]}]}'
    assert paths == ["/v2.1/Login/Autenticar", "/v2.1/Empresa", "/v2.1/Posicao/Garagem"]


@pytest.mark.asyncio
async def test_authentication_failure_hides_secret() -> None:
    async with httpx.AsyncClient(
        base_url="https://example.test/",
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    ) as client:
        with pytest.raises(SourceError) as error:
            await OlhoVivo(client, "private-token").snapshot()
        assert str(error.value) == "authentication_failed"
        assert "private-token" not in str(error.value)


@pytest.mark.parametrize(
    "body", [b"null", b"{}", b"not-json", b'{"l":[{"vs":[{"ta":"2026-05-01T12:00:00"}]}]}']
)
@pytest.mark.asyncio
async def test_invalid_payload_is_not_an_empty_success(body: bytes) -> None:
    async with httpx.AsyncClient(
        base_url="https://example.test/",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
    ) as client:
        source = OlhoVivo(client, "test")
        source.authenticated = True
        with pytest.raises(SourceError):
            await source.snapshot()


@pytest.mark.asyncio
async def test_cycle_collects_road_and_every_garage_and_persists_empty_response() -> None:
    source = AsyncMock(spec=OlhoVivo)
    store = AsyncMock(spec=PostgresStore)
    store.start.return_value = uuid4()
    source.company_codes.return_value = [2, 8]
    collector = Collector(source, store, IsolatedSettings())
    assert await collector.cycle(datetime.now(UTC)) is True
    assert source.snapshot.await_args_list[0].args == ()
    assert source.snapshot.await_args_list[1].args == (2,)
    assert source.snapshot.await_args_list[2].args == (8,)
    assert store.save.await_count == 3
    store.finish.assert_awaited_once_with(store.start.return_value, "success")


@pytest.mark.asyncio
async def test_bad_garage_does_not_prevent_other_companies() -> None:
    source = AsyncMock(spec=OlhoVivo)
    store = AsyncMock(spec=PostgresStore)
    store.start.return_value = uuid4()
    source.company_codes.return_value = [2, 8]
    source.snapshot.side_effect = [make_snapshot(), SourceError("http_500"), make_snapshot()]
    collector = Collector(source, store, IsolatedSettings())
    assert await collector.cycle(datetime.now(UTC)) is False
    assert source.snapshot.await_count == 3
    assert store.save.await_count == 2
    store.finish.assert_awaited_once_with(
        store.start.return_value, "origin_failure", "company_2:http_500"
    )


def make_snapshot(*, garage: bool = False, missing: bool = False) -> Snapshot:
    data = {
        "l": [
            {
                "c": "701A-10",
                "cl": 123,
                "sl": 1,
                "vs": [
                    {}
                    if missing
                    else {"p": 123, "ta": "2026-05-18T12:00:00Z", "py": -23.5, "px": -46.6}
                ],
            }
        ]
    }
    body = json.dumps(data).encode()
    return Snapshot(
        endpoint="/Posicao/Garagem" if garage else "/Posicao",
        company=1 if garage else None,
        collected_at=datetime.now(UTC),
        body=body,
        positions=Positions.model_validate_json(body),
    )
