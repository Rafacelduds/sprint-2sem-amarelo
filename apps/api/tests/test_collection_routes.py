from datetime import UTC, datetime, timedelta

import httpx
import pytest
from api.backup.routes import get_sessions
from api.collection.models import CollectionCycle
from api.collection.store import PostgresStore
from api.config import get_settings
from api.main import create_app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_collection import make_snapshot
from test_collection_postgres import sessions as sessions  # noqa: F401


async def test_collection_requires_auth_before_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPERATIONS_TOKEN", "test-operations")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_sessions] = lambda: (_ for _ in ()).throw(AssertionError())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = await c.get("/operations/collection", headers=headers)
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store"
    finally:
        get_settings.cache_clear()


async def test_collection_restart_counts_and_staleness(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPERATIONS_TOKEN", "test-operations")
    get_settings.cache_clear()
    store = PostgresStore(sessions)
    cycle = await store.start(datetime.now(UTC))
    await store.save(cycle, make_snapshot())
    await store.finish(cycle, "success")
    app = create_app()
    try:
        for _ in range(2):
            app = create_app()
            app.dependency_overrides[get_sessions] = lambda: sessions
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as c:
                response = await c.get(
                    "/operations/collection", headers={"Authorization": "Bearer test-operations"}
                )
                data = response.json()
                assert data["recent_activity"]
                assert data["cycles"][0]["positions"] == 1
                assert data["cycles"][0]["snapshots"] == 1
                assert data["last_success_at"]
                assert "body" not in response.text
                assert response.headers["cache-control"] == "no-store"
        async with sessions.begin() as session:
            row = await session.get(CollectionCycle, cycle)
            assert row is not None
            row.scheduled_at = row.finished_at = datetime.now(UTC) - timedelta(hours=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            data = (
                await c.get(
                    "/operations/collection", headers={"Authorization": "Bearer test-operations"}
                )
            ).json()
            assert not data["recent_activity"]
            assert data["cycles"][0]["collected_at"]
    finally:
        get_settings.cache_clear()


async def test_simulated_failure_recovery_is_persistent_and_sanitized(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulação em schema isolado: nenhum envio externo ou alteração de ciclos reais."""
    from api.collection.diagnostics import CycleDiagnostics

    monkeypatch.setenv("OPERATIONS_TOKEN", "test-operations")
    get_settings.cache_clear()
    store = PostgresStore(sessions)
    failure = await store.start(datetime.now(UTC) - timedelta(minutes=12))
    await store.record_diagnostics(
        failure,
        CycleDiagnostics(
            status="origin_failure",
            rounds=6,
            road_saved=True,
            failures={"road": "https://secret.invalid/private-token:http_500"},
        ),
    )
    await store.finish(failure, "origin_failure")
    try:
        for recovered in (False, True):
            if recovered:
                success = await store.start(datetime.now(UTC))
                await store.finish(success, "success")
            app = create_app()
            app.dependency_overrides[get_sessions] = lambda: sessions
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as c:
                response = await c.get(
                    "/operations/collection", headers={"Authorization": "Bearer test-operations"}
                )
                failed = next(row for row in response.json()["cycles"] if row["id"] == str(failure))
                assert bool(failed["recovered_at"]) == recovered
                assert failed["outage_seconds"] >= 720
                assert "HTTP 500" in str(failed["diagnostics"])
                assert "5 rodadas de retentativa" in str(failed["diagnostics"])
                assert "secret.invalid" not in response.text
                assert "private-token" not in response.text
                assert failed["alert_delivered_at"] is None
    finally:
        get_settings.cache_clear()
