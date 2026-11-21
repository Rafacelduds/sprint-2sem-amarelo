from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from test_backup import databases as databases  # noqa: F401
from test_gtfs_migrations import alembic


async def test_retry_migration_preserves_points_and_refuses_to_drop_pending_retry(
    databases: tuple[str, str],
) -> None:
    target = databases[1]
    engine = create_async_engine(target)
    now = datetime.now(UTC)
    retry = now + timedelta(minutes=5)
    identity = uuid4()
    try:
        await alembic(target, "upgrade", "20261120_0010")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO backup_runs (id, completed_at, reference, dump_reference) "
                    "VALUES (:id, :now, '{}', '{}')"
                ),
                {"id": identity, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO backup_worker (id, heartbeat_at, retry_at) "
                    "VALUES ('daily', :now, :retry)"
                ),
                {"now": now, "retry": retry},
            )
        await alembic(target, "upgrade", "head")
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE backup_worker SET heartbeat_at = NULL"))
            assert await connection.scalar(text("SELECT retry_at FROM backup_worker")) == retry
        with pytest.raises(AssertionError, match="Falha na migração"):
            await alembic(target, "downgrade", "20261120_0010")
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20261120_0011"
            )
            assert await connection.scalar(text("SELECT retry_at FROM backup_worker")) == retry
            await connection.execute(text("UPDATE backup_worker SET retry_at = NULL"))
        await alembic(target, "downgrade", "20261120_0010")
        await alembic(target, "upgrade", "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT id FROM backup_runs")) == identity
    finally:
        await engine.dispose()
