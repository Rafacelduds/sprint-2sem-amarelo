import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from api.collection.alerts import WebhookAlert
from api.collection.models import CollectionCycle
from api.collection.runner import Clock, Collector
from api.collection.source import OlhoVivo, SourceError
from api.collection.store import PostgresStore
from pydantic import SecretStr
from test_collection import IsolatedSettings, make_snapshot


class FakeClock(Clock):
    def __init__(self) -> None:
        self.seconds = 0.0
        self.delays: list[float] = []

    def now(self) -> datetime:
        return datetime(2026, 5, 18, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def monotonic(self) -> float:
        return self.seconds

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.seconds += seconds


def fake_store() -> AsyncMock:
    store = AsyncMock(spec=PostgresStore)
    store.start.return_value = uuid4()
    store.outage.return_value = None
    return store


@pytest.mark.asyncio
async def test_company_discovery_failure_preserves_available_road_positions() -> None:
    source, store, clock = AsyncMock(spec=OlhoVivo), fake_store(), FakeClock()
    source.company_codes.side_effect = SourceError("companies_unavailable")
    snapshot = make_snapshot()
    source.snapshot.return_value = snapshot
    collector = Collector(source, store, IsolatedSettings(collection_max_retries=5), clock=clock)
    assert not await collector.cycle(clock.now())
    source.snapshot.assert_awaited_once_with(None)
    store.save.assert_awaited_once_with(store.start.return_value, snapshot)
    assert source.company_codes.await_count == 6
    store.finish.assert_awaited_once_with(
        store.start.return_value, "origin_failure", "companies:companies_unavailable"
    )


@pytest.mark.asyncio
async def test_company_discovery_recovers_without_repeating_persisted_road_positions() -> None:
    source, store, clock = AsyncMock(spec=OlhoVivo), fake_store(), FakeClock()
    source.company_codes.side_effect = [SourceError("unavailable"), [1]]
    collector = Collector(source, store, IsolatedSettings(collection_max_retries=5), clock=clock)
    assert await collector.cycle(clock.now())
    assert [call.args for call in source.snapshot.await_args_list] == [(None,), (1,)]
    assert store.save.await_count == 2


@pytest.mark.parametrize("error", [RuntimeError("finish failed"), TimeoutError()])
@pytest.mark.asyncio
async def test_persistent_finish_failure_triggers_storage_alert_and_throttles(
    error: Exception,
) -> None:
    source, store, clock = AsyncMock(spec=OlhoVivo), fake_store(), FakeClock()
    source.company_codes.return_value = [1]
    store.finish.side_effect = error
    alert = AsyncMock(spec=WebhookAlert)
    collector = Collector(source, store, IsolatedSettings(), clock=clock, alert=alert)
    started = clock.now()
    assert not await collector.cycle(clock.now())
    clock.seconds = 599
    assert not await collector.cycle(clock.now())
    alert.send.assert_not_awaited()
    clock.seconds = 601
    assert not await collector.cycle(clock.now())
    alert.send.assert_awaited_once_with(UUID(int=0), started)
    assert not await collector.cycle(clock.now())
    assert alert.send.await_count == 1
    clock.seconds = 661
    assert not await collector.cycle(clock.now())
    assert alert.send.await_count == 2


@pytest.mark.asyncio
async def test_five_retries_only_repeat_failed_endpoint() -> None:
    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [1]
    source.snapshot.side_effect = [make_snapshot()] + [SourceError("http_500")] * 6
    store, clock = fake_store(), FakeClock()
    collector = Collector(source, store, IsolatedSettings(collection_max_retries=5), clock=clock)
    assert not await collector.cycle(clock.now())
    assert source.snapshot.await_count == 7  # uma operação + seis tentativas da garagem
    assert clock.delays == [1, 2, 4, 8, 16]
    assert store.save.await_count == 1
    store.finish.assert_awaited_once_with(
        store.start.return_value, "origin_failure", "company_1:http_500"
    )


@pytest.mark.asyncio
async def test_transient_failure_recovers_without_inventing_positions() -> None:
    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [1]
    source.snapshot.side_effect = [
        make_snapshot(),
        SourceError("timeout"),
        make_snapshot(garage=True),
    ]
    store, clock = fake_store(), FakeClock()
    collector = Collector(source, store, IsolatedSettings(collection_max_retries=5), clock=clock)
    assert await collector.cycle(clock.now())
    assert store.save.await_count == 2
    assert clock.delays == [1]
    store.finish.assert_awaited_once_with(store.start.return_value, "success", None)


@pytest.mark.asyncio
async def test_expired_session_reauthenticates_on_retry() -> None:
    logins, garage_calls = 0, 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal logins, garage_calls
        if request.url.path.endswith("Autenticar"):
            logins += 1
            return httpx.Response(200, json=True)
        if request.url.path.endswith("Garagem"):
            garage_calls += 1
            if garage_calls == 1:
                return httpx.Response(401)
        return httpx.Response(200, json={"l": []})

    async with httpx.AsyncClient(
        base_url="https://test.invalid/", transport=httpx.MockTransport(handler)
    ) as client:
        collector = Collector(
            OlhoVivo(client, "secret"),
            fake_store(),
            IsolatedSettings(collection_max_retries=5, collection_company_codes=[1]),
            clock=FakeClock(),
        )
        assert await collector.cycle(datetime.now(UTC))
    assert logins == 2 and garage_calls == 2


@pytest.mark.asyncio
async def test_cycle_deadline_cancels_slow_origin() -> None:
    async def slow() -> list[int]:
        await asyncio.sleep(10)
        return [1]

    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.side_effect = slow
    store = fake_store()
    collector = Collector(source, store, IsolatedSettings(collection_cycle_budget_seconds=0.01))
    assert not await collector.cycle(datetime.now(UTC))
    store.finish.assert_awaited_once_with(
        store.start.return_value, "origin_failure", "cycle_deadline"
    )


@pytest.mark.asyncio
async def test_storage_error_is_not_counted_as_origin_failure() -> None:
    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [1]
    store = fake_store()
    store.save.side_effect = RuntimeError("storage failed")
    collector = Collector(source, store, IsolatedSettings(collection_max_retries=5))
    assert not await collector.cycle(datetime.now(UTC))
    assert source.snapshot.await_count == 1
    store.finish.assert_awaited_once_with(
        store.start.return_value, "storage_failure", "persistence_failed"
    )


@pytest.mark.asyncio
async def test_alert_after_ten_minutes_is_confirmed_and_throttled() -> None:
    clock, store = FakeClock(), fake_store()
    outage = CollectionCycle(id=uuid4(), scheduled_at=clock.now(), status="origin_failure")
    store.outage.return_value = outage
    alert = AsyncMock(spec=WebhookAlert)
    alert.send.return_value = True
    collector = Collector(
        AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock, alert=alert
    )
    clock.seconds = 599
    await collector.notify_outage()
    alert.send.assert_not_awaited()
    clock.seconds = 600
    await collector.notify_outage()
    alert.send.assert_awaited_once_with(outage.id, outage.scheduled_at)
    store.mark_alerted.assert_awaited_once_with(outage.id, clock.now())
    await collector.notify_outage()
    assert alert.send.await_count == 1


@pytest.mark.asyncio
async def test_failed_webhook_is_not_marked_delivered_and_retries_later() -> None:
    clock, store = FakeClock(), fake_store()
    store.outage.return_value = CollectionCycle(
        id=uuid4(), scheduled_at=clock.now(), status="origin_failure"
    )
    clock.seconds = 600
    alert = AsyncMock(spec=WebhookAlert)
    alert.send.return_value = False
    collector = Collector(
        AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock, alert=alert
    )
    await collector.notify_outage()
    await collector.notify_outage()
    assert alert.send.await_count == 1
    store.mark_alerted.assert_not_awaited()
    clock.seconds = 660
    await collector.notify_outage()
    assert alert.send.await_count == 2


@pytest.mark.asyncio
async def test_webhook_request_and_failure_hide_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    real_client = httpx.AsyncClient

    def make_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("api.collection.alerts.httpx.AsyncClient", make_client)
    alert = WebhookAlert(SecretStr("https://test.invalid/private-webhook"))
    assert await alert.send(uuid4(), datetime.now(UTC))
    assert len(calls) == 1 and calls[0].method == "POST"
    assert b'"event":"collection_outage"' in calls[0].content


@pytest.mark.asyncio
async def test_scheduler_resumes_after_failed_cycle() -> None:
    store, clock = fake_store(), FakeClock()
    collector = Collector(AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock)
    collector.cycle = AsyncMock(side_effect=[False, True, asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await collector.run()
    assert collector.cycle.await_count == 3
    assert clock.delays == [30, 30]


@pytest.mark.asyncio
async def test_no_webhook_is_not_a_delivery() -> None:
    assert not await WebhookAlert(None).send(uuid4(), datetime.now(UTC))


@pytest.mark.asyncio
async def test_webhook_failure_does_not_leak_secret_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_client = httpx.AsyncClient

    def make_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    monkeypatch.setattr("api.collection.alerts.httpx.AsyncClient", make_client)
    assert not await WebhookAlert(SecretStr("https://test.invalid/private-secret")).send(
        uuid4(), datetime.now(UTC)
    )
    assert "private-secret" not in caplog.text
    assert "collection_webhook_delivery_failed" in caplog.text


@pytest.mark.asyncio
async def test_database_outage_is_recorded_when_storage_recovers() -> None:
    clock, store = FakeClock(), fake_store()
    first_id, gap_id = uuid4(), uuid4()
    store.start.side_effect = [RuntimeError("offline"), first_id, gap_id]
    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [1]
    collector = Collector(source, store, IsolatedSettings(), clock=clock)
    assert not await collector.cycle(clock.now())
    clock.seconds = 30
    assert await collector.cycle(clock.now())
    assert collector.storage_down_since is None
    assert store.start.await_args_list[2].args == (datetime(2026, 5, 18, tzinfo=UTC),)
    assert store.finish.await_args_list[0].args == (
        gap_id,
        "storage_failure",
        "database_unavailable",
    )


@pytest.mark.asyncio
async def test_hung_storage_is_not_excluded_as_origin_failure() -> None:
    async def slow_save(*args: object) -> None:
        await asyncio.sleep(10)

    source, store = AsyncMock(spec=OlhoVivo), fake_store()
    source.company_codes.return_value = [1]
    store.save.side_effect = slow_save
    collector = Collector(source, store, IsolatedSettings(collection_cycle_budget_seconds=0.01))
    assert not await collector.cycle(datetime.now(UTC))
    store.finish.assert_awaited_once_with(
        store.start.return_value, "storage_failure", "cycle_deadline"
    )
