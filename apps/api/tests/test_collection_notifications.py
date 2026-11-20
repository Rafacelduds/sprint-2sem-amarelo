from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.collection.alerts import WebhookAlert
from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle
from api.collection.runner import Collector
from api.collection.source import OlhoVivo, SourceError
from api.collection.store import RecoveryNotice
from test_collection import IsolatedSettings, make_snapshot
from test_collection_resilience import FakeClock, fake_store


@pytest.mark.asyncio
async def test_persists_partial_cycle_diagnostics_and_actual_retry_rounds() -> None:
    clock, store, source = FakeClock(), fake_store(), AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [600, 602]
    source.snapshot.side_effect = [
        make_snapshot(),
        make_snapshot(garage=True),
        SourceError("/Posicao/Garagem:http_500"),
    ]
    collector = Collector(source, store, IsolatedSettings(), clock=clock)
    assert not await collector.cycle(clock.now())
    details = store.record_diagnostics.await_args.args[1]
    assert isinstance(details, CycleDiagnostics)
    assert details.road_saved and details.garages_saved == 1
    assert details.rounds == 1 and details.companies_discovered
    assert details.failures == {"company_602": "/Posicao/Garagem:http_500"}


@pytest.mark.asyncio
async def test_alert_uses_latest_failure_instead_of_first_failure_details() -> None:
    clock, store, alert = FakeClock(), fake_store(), AsyncMock(spec=WebhookAlert)
    outage = CollectionCycle(id=uuid4(), scheduled_at=clock.now(), status="origin_failure")
    details = CycleDiagnostics(
        status="origin_failure",
        rounds=6,
        road_saved=True,
        garages_saved=8,
        companies_discovered=True,
        failures={"company_600": "http_500"},
    )
    latest = CollectionCycle(
        id=uuid4(),
        scheduled_at=clock.now() + timedelta(minutes=9),
        status="origin_failure",
        diagnostics=details.model_dump(),
    )
    store.outage.return_value = outage
    store.latest_failure.return_value = latest
    clock.seconds = 600
    collector = Collector(
        AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock, alert=alert
    )
    await collector.notify_outage()
    alert.send.assert_awaited_once_with(
        outage.id, outage.scheduled_at, diagnostics=details, observed_at=clock.now()
    )
    alert.send_recovery.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_requires_confirmation_and_retries_without_repeating_failure() -> None:
    clock, store, alert = FakeClock(), fake_store(), AsyncMock(spec=WebhookAlert)
    outage = CollectionCycle(id=uuid4(), scheduled_at=clock.now(), status="origin_failure")
    recovered_at = clock.now() + timedelta(minutes=12)
    store.pending_recovery.return_value = RecoveryNotice(outage, recovered_at)
    alert.send_recovery.side_effect = [False, True]
    collector = Collector(
        AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock, alert=alert
    )
    await collector.notify_outage()
    store.mark_recovery_alerted.assert_not_awaited()
    await collector.notify_outage()
    assert alert.send_recovery.await_count == 1
    clock.seconds = 60
    await collector.notify_outage()
    store.mark_recovery_alerted.assert_awaited_once_with(outage.id, clock.now())
    store.pending_recovery.return_value = None
    await collector.notify_outage()
    assert alert.send_recovery.await_count == 2
    alert.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_green_recovery_message_while_another_outage_is_active() -> None:
    clock, store, alert = FakeClock(), fake_store(), AsyncMock(spec=WebhookAlert)
    outage = CollectionCycle(
        id=uuid4(), scheduled_at=clock.now(), status="origin_failure", alerted_at=clock.now()
    )
    store.outage.return_value = outage
    store.pending_recovery.return_value = RecoveryNotice(outage, clock.now())
    collector = Collector(
        AsyncMock(spec=OlhoVivo), store, IsolatedSettings(), clock=clock, alert=alert
    )
    await collector.notify_outage()
    alert.send_recovery.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_fallback_confirmation_is_journaled_for_later_recovery() -> None:
    clock, store, alert = FakeClock(), fake_store(), AsyncMock(spec=WebhookAlert)
    current_id, gap_id = uuid4(), uuid4()
    store.start.side_effect = [RuntimeError("offline"), RuntimeError("offline"), current_id, gap_id]
    alert.send.return_value = True
    source = AsyncMock(spec=OlhoVivo)
    source.company_codes.return_value = [1]
    collector = Collector(source, store, IsolatedSettings(), clock=clock, alert=alert)
    collector.storage_incident_id = gap_id
    assert not await collector.cycle(clock.now())
    clock.seconds = 601
    assert not await collector.cycle(clock.now())
    assert collector.storage_alerted_at == clock.now()
    alerted_at = clock.now()
    clock.seconds = 650
    assert await collector.cycle(clock.now())
    store.mark_alerted.assert_awaited_once_with(gap_id, alerted_at)
    assert store.start.await_args.kwargs == {"cycle_id": gap_id}
    assert alert.send.await_args.args[0] == gap_id
    assert collector.storage_down_since is None and collector.storage_alerted_at is None


def test_unknown_storage_impact_is_not_reported_as_zero_data() -> None:
    sections = CycleDiagnostics(status="storage_failure").sections()
    assert "indisponível" in sections["Coleta preservada · último ciclo"]
    assert "nenhuma resposta" not in sections["Coleta preservada · último ciclo"]
    assert "banco" in sections["Ação sugerida"]


def test_untrusted_error_detail_does_not_appear_in_human_message() -> None:
    details = CycleDiagnostics(
        status="origin_failure",
        failures={"company_600": "http_500 https://private-token.invalid @everyone"},
    )
    text = str(details.sections())
    assert "HTTP 500" in text and "600" in text
    assert "private-token" not in text and "@everyone" not in text
