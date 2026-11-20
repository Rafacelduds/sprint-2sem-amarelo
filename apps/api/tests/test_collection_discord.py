import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from api.collection import __main__ as cli
from api.collection.alerts import WebhookAlert
from api.collection.diagnostics import CycleDiagnostics
from api.collection.runner import Collector
from api.collection.source import OlhoVivo
from api.collection.store import PostgresStore
from pydantic import SecretStr, ValidationError
from test_collection import IsolatedSettings

WEBHOOK = "https://discord.com/api/webhooks/123/private-token"
START = datetime(2026, 11, 19, 15, tzinfo=UTC)
CYCLE = UUID(int=42)


class Receiver:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response = httpx.Response(200, json={"id": "987654"})
        self.timeout = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.timeout:
            raise httpx.ReadTimeout("private-token", request=request)
        return self.response


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Receiver:
    result = Receiver()
    real_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(result.handle))

    monkeypatch.setattr("api.collection.alerts.httpx.AsyncClient", client)
    return result


@pytest.mark.asyncio
async def test_discord_content_time_mentions_and_confirmation(receiver: Receiver) -> None:
    alert = WebhookAlert(SecretStr(WEBHOOK + "?wait=false&thread_id=456"), "discord")
    assert await alert.send(CYCLE, START)
    request = receiver.requests[0]
    assert request.url.params["wait"] == "true"
    assert request.url.params["thread_id"] == "456"
    payload = json.loads(request.content)
    embed = payload["embeds"][0]
    assert embed["fields"][0]["value"] == "19/11/2026 12:00:00"
    assert str(CYCLE) in embed["footer"]["text"]
    assert "dez minutos" in embed["description"]
    assert embed["color"] == 0xED4245
    assert payload["allowed_mentions"] == {"parse": []}
    assert "private-token" not in request.content.decode()


@pytest.mark.asyncio
async def test_rich_failure_and_recovery_are_readable_and_bounded(receiver: Receiver) -> None:
    from datetime import timedelta

    alert = WebhookAlert(SecretStr(WEBHOOK), "discord")
    details = CycleDiagnostics(
        status="origin_failure",
        rounds=6,
        road_saved=True,
        garages_saved=8,
        companies_discovered=True,
        failures={"company_600": "/Posicao/Garagem:http_500"},
    )
    recovered = START + timedelta(minutes=12)
    assert await alert.send(CYCLE, START, diagnostics=details, observed_at=recovered)
    failure = json.loads(receiver.requests[-1].content)
    assert "HTTP 500" in str(failure) and "600" in str(failure)
    assert "resposta gravada" in str(failure) and "retentativa" in str(failure)
    assert "12 min" in str(failure)
    assert await alert.send_recovery(CYCLE, START, recovered)
    recovery = json.loads(receiver.requests[-1].content)
    assert recovery["embeds"][0]["color"] == 0x57F287
    assert str(CYCLE) in recovery["embeds"][0]["footer"]["text"]
    assert "lacunas" in recovery["embeds"][0]["description"]
    for payload in (failure, recovery):
        embed = payload["embeds"][0]
        assert len(embed["title"]) <= 256 and len(embed["fields"]) <= 25
        assert all(len(f["value"]) <= 1024 for f in embed["fields"])
        assert payload["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize(
    "status,body",
    [
        (204, b""),
        (200, b"{}"),
        (200, b'{"id":""}'),
        (200, b'{"id":123}'),
        (200, b"not-json"),
        (400, b"{}"),
        (401, b"{}"),
        (404, b"{}"),
        (500, b"{}"),
    ],
)
@pytest.mark.asyncio
async def test_unconfirmed_or_failed_delivery_is_false(
    receiver: Receiver,
    status: int,
    body: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    receiver.response = httpx.Response(status, content=body)
    assert not await WebhookAlert(SecretStr(WEBHOOK), "discord").send(CYCLE, START)
    assert "private-token" not in caplog.text


@pytest.mark.asyncio
async def test_discord_timeout_hides_url(
    receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    receiver.timeout = True
    assert not await WebhookAlert(SecretStr(WEBHOOK), "discord").send(CYCLE, START)
    assert "private-token" not in caplog.text


@pytest.mark.parametrize("body", [b'{"retry_after":120}', b"invalid-json"])
@pytest.mark.asyncio
async def test_rate_limit_does_not_send_again_before_cooldown(
    receiver: Receiver, body: bytes
) -> None:
    receiver.response = httpx.Response(429, content=body)
    alert = WebhookAlert(SecretStr(WEBHOOK), "discord")
    assert not await alert.send(CYCLE, START)
    assert not await alert.send(CYCLE, START)
    assert len(receiver.requests) == 1
    alert.retry_at = 0  # simula fim do intervalo, sem esperar em tempo real
    receiver.response = httpx.Response(200, json={"id": "123"})
    assert await alert.send(CYCLE, START)


@pytest.mark.asyncio
async def test_no_discord_url_does_not_send(receiver: Receiver) -> None:
    assert not await WebhookAlert(None, "discord").send(CYCLE, START)
    assert not receiver.requests


def test_format_is_explicit_and_defaults_to_generic() -> None:
    assert IsolatedSettings().collection_alert_format == "generic"
    with pytest.raises(ValidationError):
        IsolatedSettings.model_validate({"collection_alert_format": "unknown"})
    collector = Collector(
        AsyncMock(spec=OlhoVivo),
        AsyncMock(spec=PostgresStore),
        IsolatedSettings(collection_alert_format="discord"),
    )
    assert collector.alert.webhook_format == "discord"


@pytest.mark.parametrize("flag", ["--test-alert", "--test-failure-alert", "--test-recovery-alert"])
@pytest.mark.asyncio
async def test_cli_sends_labeled_test_without_database_or_sptrans(
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    monkeypatch.setattr("sys.argv", ["collection", flag])
    monkeypatch.setattr(
        cli,
        "CollectionSettings",
        lambda: IsolatedSettings(
            collection_alert_format="discord", collection_alert_webhook=SecretStr(WEBHOOK)
        ),
    )

    def no_database(*args: object, **kwargs: object) -> None:
        pytest.fail("Teste de alerta não deve abrir banco nem iniciar coleta")

    monkeypatch.setattr(cli, "create_async_engine", no_database)
    await cli.main()
    assert len(receiver.requests) == 1
    embed = json.loads(receiver.requests[0].content)["embeds"][0]
    assert "TESTE" in embed["description"] or "SIMULAÇÃO" in embed["description"]
    assert "real" in embed["description"]
    assert embed["color"] == (
        0x57F287
        if flag == "--test-recovery-alert"
        else 0xFEE75C
        if flag == "--test-alert"
        else 0xED4245
    )


@pytest.mark.asyncio
async def test_cli_returns_failure_when_test_not_delivered(
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver.response = httpx.Response(500)
    monkeypatch.setattr("sys.argv", ["collection", "--test-alert"])
    monkeypatch.setattr(
        cli,
        "CollectionSettings",
        lambda: IsolatedSettings(
            collection_alert_format="discord", collection_alert_webhook=SecretStr(WEBHOOK)
        ),
    )
    with pytest.raises(SystemExit) as error:
        await cli.main()
    assert error.value.code == 1
