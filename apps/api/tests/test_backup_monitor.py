from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from api.backup.models import BackupAttempt, BackupRun, BackupWorker
from api.backup.monitor import pulse, record_attempt
from api.backup.routes import get_sessions
from api.backup.service import BackupService
from api.config import get_settings
from api.main import create_app
from api.storage.contracts import ObjectRef
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_backup import databases as databases  # noqa: F401


@pytest.fixture
def protected_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setenv("OPERATIONS_TOKEN", "private-test-key")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


async def test_access_is_denied_before_any_database_read(protected_app: FastAPI) -> None:
    app = protected_app
    app.dependency_overrides[get_sessions] = lambda: (_ for _ in ()).throw(AssertionError())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            response = await client.get("/operations/backups", headers=headers)
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
            assert "private-test-key" not in response.text
    get_settings().operations_token = SecretStr("")
    app.dependency_overrides.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.get(
                "/operations/backups", headers={"Authorization": "Bearer private-test-key"}
            )
        ).status_code == 401


async def test_status_uses_persisted_evidence_and_redacts_storage(
    protected_app: FastAPI, databases: tuple[str, str]
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    protected_app.dependency_overrides[get_sessions] = lambda: sessions
    now = datetime.now(UTC)
    identity = uuid4()
    secret_ref = {"sha256": "a" * 64, "bucket": "private-bucket", "key": "secret.dump"}
    async with sessions.begin() as session:
        session.add(
            BackupRun(
                id=identity,
                completed_at=now - timedelta(days=3),
                reference=secret_ref,
                dump_reference=secret_ref,
            )
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=protected_app), base_url="http://test"
    ) as client:
        headers = {"Authorization": "Bearer private-test-key"}
        data = (await client.get("/operations/backups", headers=headers)).json()
        assert not data["worker_active"] and data["overdue"]
        assert data["points"][0]["verified_at_creation"] is None
        assert data["next_execution"] is None
        assert not any(
            secret in str(data) for secret in ("private-bucket", "secret.dump", "private-test-key")
        )
        await pulse(sessions)
        async with sessions.begin() as session:
            session.add(
                BackupAttempt(
                    id=uuid4(),
                    started_at=now,
                    finished_at=now,
                    status="success",
                    backup_id=identity,
                )
            )
        data = (await client.get("/operations/backups", headers=headers)).json()
        assert data["worker_active"]
        assert data["points"][0]["verified_at_creation"]
        async with sessions.begin() as session:
            worker = await session.get(BackupWorker, "daily")
            assert worker is not None
            worker.heartbeat_at = now - timedelta(seconds=121)
        data = (await client.get("/operations/backups", headers=headers)).json()
        assert not data["worker_active"]
        async with sessions.begin() as session:
            worker = await session.get(BackupWorker, "daily")
            assert worker is not None
            worker.heartbeat_at = None
            worker.retry_at = now + timedelta(minutes=5)
        data = (await client.get("/operations/backups", headers=headers)).json()
        assert not data["worker_active"] and data["next_execution"] is None
        assert data["heartbeat_at"] is None
    await engine.dispose()


async def test_attempt_failure_is_persisted_without_exception_secrets(
    databases: tuple[str, str],
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = cast(
        BackupService,
        SimpleNamespace(
            sessions=sessions,
            create=AsyncMock(side_effect=RuntimeError("postgres://private-password@internal")),
        ),
    )
    with pytest.raises(RuntimeError):
        await record_attempt(service, "a" * 40)
    async with sessions() as session:
        attempt = await session.scalar(select(BackupAttempt))
        assert attempt is not None and attempt.status == "failed"
        assert attempt.finished_at is not None and attempt.backup_id is None
    await engine.dispose()


async def test_success_links_to_real_point_only_after_service_returns(
    databases: tuple[str, str],
) -> None:
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identity = uuid4()
    ref = ObjectRef(
        bucket="backup",
        key=f"backups/runs/{identity}.json",
        sha256="a" * 64,
        stored_sha256="a" * 64,
        size=1,
        stored_size=1,
    )

    async def create(_: str) -> ObjectRef:
        async with sessions.begin() as session:
            session.add(
                BackupRun(
                    id=identity,
                    completed_at=datetime.now(UTC),
                    reference=ref.model_dump(mode="json"),
                    dump_reference={},
                )
            )
        return ref

    service = cast(BackupService, SimpleNamespace(sessions=sessions, create=create))
    await record_attempt(service, "a" * 40)
    async with sessions() as session:
        attempt = await session.scalar(select(BackupAttempt))
        assert attempt is not None and attempt.status == "success" and attempt.backup_id == identity
    await engine.dispose()
