import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta, tzinfo
from unittest.mock import Mock
from uuid import uuid4

import pytest
from api.backup import __main__ as cli
from api.backup import monitor
from api.backup.__main__ import BackupSettings
from api.backup.models import BackupAttempt, BackupRun, BackupWorker
from api.backup.service import BackupService
from api.config import Settings
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_backup import databases as databases  # noqa: F401


async def test_heartbeat_recovers_without_leaking_errors_and_still_cancels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recovered = asyncio.Event()
    calls = 0

    async def intermittent_pulse(_: async_sessionmaker[AsyncSession]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private-password@internal-host")
        recovered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(monitor, "pulse", intermittent_pulse)
    monkeypatch.setattr(monitor, "HEARTBEAT_SECONDS", 0)
    ticker = asyncio.create_task(monitor.heartbeat(Mock()))
    observation = asyncio.create_task(recovered.wait())
    try:
        await asyncio.wait([ticker, observation], timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert recovered.is_set(), "O heartbeat não retomou após uma falha transitória"
        assert not ticker.done()
        assert "private-password" not in caplog.text and "internal-host" not in caplog.text
        ticker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ticker
    finally:
        ticker.cancel()
        observation.cancel()
        with suppress(asyncio.CancelledError, RuntimeError):
            await ticker
        with suppress(asyncio.CancelledError):
            await observation


class StopScheduler(BaseException):
    pass


@pytest.mark.parametrize("scenario", ["post_catalog_failure", "restart_pending", "stop_pending"])
async def test_watch_honors_retry_after_commit_restart_and_normal_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    databases: tuple[str, str],
    scenario: str,
) -> None:
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    scheduled = now + timedelta(seconds=120)
    engine = create_async_engine(databases[0])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = BackupSettings(database_url=databases[0], app_code_version="a" * 40)
    calls: list[datetime] = []
    waits: list[float] = []
    original_sleep = asyncio.sleep

    class Clock:
        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            return now.astimezone(tz)

    async def simulated_backup(self: BackupService, _: str) -> ObjectRef:
        calls.append(now)
        identity = uuid4()
        ref = ObjectRef(
            bucket="secondary",
            key=f"backups/runs/{identity}.json",
            sha256="a" * 64,
            stored_sha256="a" * 64,
            size=1,
            stored_size=1,
        )
        async with self.sessions.begin() as session:
            session.add(
                BackupRun(
                    id=identity,
                    completed_at=now,
                    reference=ref.model_dump(mode="json"),
                    dump_reference={},
                )
            )
        if scenario == "post_catalog_failure" and len(calls) == 1:
            raise RuntimeError("cleanup failed after catalog commit")
        return ref

    async def controlled_sleep(delay: float) -> None:
        nonlocal now
        if delay == 300:
            waits.append(delay)
            now += timedelta(seconds=delay)
            await original_sleep(0)
        elif delay == 60:
            if calls or scenario == "stop_pending":
                raise StopScheduler()
            now += timedelta(seconds=delay)
            await original_sleep(0)
        else:
            await original_sleep(3600 if delay == 30 else 0)

    def primary(_: Settings) -> S3Archive:
        return Mock(spec=S3Archive, bucket="primary")

    def secondary(_: BackupSettings) -> S3Archive:
        return Mock(spec=S3Archive, bucket="secondary")

    try:
        if scenario != "post_catalog_failure":
            async with sessions.begin() as session:
                session.add(
                    BackupRun(id=uuid4(), completed_at=now, reference={}, dump_reference={})
                )
                session.add(BackupWorker(id="daily", heartbeat_at=now, retry_at=scheduled))
        monkeypatch.setattr(cli, "BackupSettings", lambda: settings)
        monkeypatch.setattr(cli, "datetime", Clock)
        monkeypatch.setattr(cli, "archive_from_settings", primary)
        monkeypatch.setattr(cli, "backup_from_settings", secondary)
        monkeypatch.setattr(BackupService, "create", simulated_backup)
        monkeypatch.setattr("sys.argv", ["backup", "watch"])
        monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
        with pytest.raises(StopScheduler):
            await cli.main()
        async with sessions() as session:
            worker = await session.get(BackupWorker, "daily")
            assert worker is not None and worker.heartbeat_at is None
            if scenario == "post_catalog_failure":
                assert len(calls) == 2 and waits == [300]
                assert calls[1] - calls[0] == timedelta(seconds=300)
                assert worker.retry_at is None
                statuses = list((await session.scalars(select(BackupAttempt.status))).all())
                assert sorted(statuses) == ["failed", "success"]
            elif scenario == "restart_pending":
                assert calls == [scheduled], "Não pode antecipar nem ignorar o retry persistido"
                assert worker.retry_at is None
            else:
                assert not calls and worker.retry_at == scheduled
    finally:
        await engine.dispose()
