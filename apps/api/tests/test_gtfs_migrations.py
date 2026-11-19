"""Upgrade das duas linhas de migração publicadas, preservando posições existentes."""

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def alembic(database_url: str, action: str, target: str | None = None) -> None:
    root = Path(__file__).resolve().parents[3]
    args = [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", action]
    if target is not None:
        args.append(target)
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=root,
        env={**os.environ, "DATABASE_URL": database_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(process.communicate(), timeout=90)
    # Não incluir saídas de bibliotecas que possam conter URLs ou credenciais.
    assert process.returncode == 0, f"Falha na migração: {action} {target or ''}"


@pytest.mark.parametrize(
    "starting_revision",
    ["7ad978e014e5", "20261118_0002", "b12000000001", "20261118_0004", "b32000000001"],
)
async def test_upgrade_from_each_published_branch_preserves_positions(
    starting_revision: str,
) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada: requer PostgreSQL exclusivo de testes")
    # O PostgreSQL de testes precisa permitir CREATE DATABASE; a CI usa instância própria.
    name = "test_gtfs_migration_" + uuid4().hex
    target_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_async_engine(target_url)
    try:
        await alembic(target_url, "upgrade", starting_revision)
        cycle_id, snapshot_id, position_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO collection_cycles (id, scheduled_at, status) "
                    "VALUES (:id, :at, 'success')"
                ),
                {"id": cycle_id, "at": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO collection_snapshots "
                    "(id, cycle_id, endpoint, collected_at, body) "
                    "VALUES (:id, :cycle, '/Posicao', :at, :body)"
                ),
                {"id": snapshot_id, "cycle": cycle_id, "at": now, "body": b'{"l":[]}'},
            )
            columns = "id, snapshot_id, prefix, gps_at, collected_at, in_garage"
            values = ":id, :snapshot, 'legacy', :at, :at, false"
            if starting_revision in {"20261118_0002", "20261118_0004"}:
                columns += ", gtfs_link_status"
                values += ", 'no_gtfs_for_date'"
            await connection.execute(
                text(f"INSERT INTO vehicle_positions ({columns}) VALUES ({values})"),
                {"id": position_id, "snapshot": snapshot_id, "at": now},
            )
        await alembic(target_url, "upgrade", "head")
        await alembic(target_url, "check")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20261119_0008"
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT prefix, gtfs_version_sha256, gtfs_link_status "
                        "FROM vehicle_positions WHERE id = :id"
                    ),
                    {"id": position_id},
                )
            ).one()
            assert row.prefix == "legacy" and row.gtfs_version_sha256 is None
            assert row.gtfs_link_status == (
                "no_gtfs_for_date"
                if starting_revision in {"20261118_0002", "20261118_0004"}
                else "not_evaluated"
            )
            await connection.execute(text("SELECT alerted_at FROM collection_cycles"))
        # Reversão só no banco descartável: preserva as tabelas e os dados da US01.
        await alembic(target_url, "downgrade", "34bf95c97f11")
        await alembic(target_url, "upgrade", "head")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT prefix FROM vehicle_positions WHERE id = :id"), {"id": position_id}
                )
                == "legacy"
            )
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
