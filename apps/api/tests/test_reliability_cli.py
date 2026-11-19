"""Publicação pela CLI e consulta HTTP real em banco e porta exclusivos."""

import asyncio
import json
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from api.storage.s3 import S3Archive
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from test_gtfs_migrations import alembic
from test_storage import archive as archive  # noqa: F401


async def test_cli_publish_and_real_public_http(archive: S3Archive) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada")
    name = "test_us13_cli_" + uuid4().hex
    target = make_url(url).set(database=name).render_as_string(hide_password=False)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    root = Path(__file__).resolve().parents[3]
    day = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=1)
    env = {
        **os.environ,
        "DATABASE_URL": target,
        "S3_ENDPOINT_URL": archive.client.meta.endpoint_url,
        "S3_BUCKET": archive.bucket,
        "S3_ACCESS_KEY": "test",
        "S3_SECRET_KEY": "test",
        "S3_RESTORE_MAP": str(root / "infra/storage/empty-restore-map.json"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    server: asyncio.subprocess.Process | None = None
    try:
        await alembic(target, "upgrade", "head")
        command = await asyncio.create_subprocess_exec(
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "api.reliability",
            "--day",
            day.isoformat(),
            "--code-version",
            "a" * 40,
            cwd=root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, _ = await asyncio.wait_for(command.communicate(), 90)
        assert command.returncode == 0, "CLI de publicação falhou"
        published = json.loads(output)
        assert published["gap_seconds"] == 86400
        assert published["code_version"] == "a" * 40
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = await asyncio.create_subprocess_exec(
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            cwd=root,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False
        ) as client:
            for _ in range(100):
                try:
                    response = await client.get("/health", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
            response = await client.get(f"/reports/reliability/{day.isoformat()}")
            assert response.status_code == 200 and response.json() == published
            missing = day - timedelta(days=1)
            assert (await client.get(f"/reports/reliability/{missing}")).status_code == 404
        await alembic(target, "downgrade", "20261118_0005")
        await alembic(target, "upgrade", "head")
        await alembic(target, "check")
    finally:
        if server is not None and server.returncode is None:
            server.terminate()
            await asyncio.wait_for(server.wait(), 15)
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
