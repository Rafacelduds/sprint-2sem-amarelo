import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from api.documents.contracts import DocumentMetadata, RegistrationResult
from api.documents.models import OfficialDocument
from api.documents.service import DocumentCatalogue
from api.storage.models import RawObject
from api.storage.s3 import S3Archive
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_gtfs_migrations import alembic
from test_storage import archive as archive  # noqa: F401

PDF = b"%PDF-1.4\n% fixture de preservacao de bytes\n%%EOF\n"
METADATA = DocumentMetadata(
    title="Ficha ICF",
    document_type="ficha_indicador",
    document_date=date(2021, 9, 1),
    source="Recebido do cliente; pasta compartilhada de documentos",
    notes="Órgão emissor ainda não confirmado.",
)


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", " "),
        ("agency", ""),
        ("document_type", "outro"),
        ("source", ""),
        ("document_date", "2026-02-30"),
        ("extra", True),
    ],
)
def test_invalid_metadata(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate({**METADATA.model_dump(), field: value})


async def test_original_persistence_renamed_duplicate_and_conflict(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    path = tmp_path / "ficha técnica.pdf"
    path.write_bytes(PDF)
    catalogue = DocumentCatalogue(sessions, archive)
    first = await catalogue.register(path, METADATA)
    assert first.created
    assert first.document.agency is None
    assert first.document.document_date == date(2021, 9, 1)
    assert first.document.catalogued_at.tzinfo is not None
    assert first.document.original.content_type == "application/pdf"
    downloaded = tmp_path / "download.pdf"
    archive.download(first.document.original, downloaded)
    assert downloaded.read_bytes() == PDF
    renamed = tmp_path / "copia-com-outro-nome.pdf"
    renamed.write_bytes(PDF)
    repeated = await DocumentCatalogue(sessions, archive).register(renamed, METADATA)
    assert not repeated.created and repeated.document == first.document
    with pytest.raises(ValueError, match="metadados diferentes"):
        await catalogue.register(path, METADATA.model_copy(update={"agency": "Outro órgão"}))
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OfficialDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(RawObject)) == 1
    versions = archive.client.list_object_versions(Bucket=archive.bucket)["Versions"]
    assert len(versions) == 1
    path.write_bytes(PDF.replace(b"fixture", b"outra versao"))
    revised = await catalogue.register(path, METADATA)
    assert revised.created and revised.document.id != first.document.id
    assert revised.document.original_filename == first.document.original_filename
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OfficialDocument)) == 2


@pytest.mark.parametrize("payload", [b"nao e PDF", b"%PDF-1.4\ntruncado"])
async def test_invalid_pdf_leaves_no_catalogue_or_object(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "invalid.pdf"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="PDF"):
        await DocumentCatalogue(sessions, archive).register(path, METADATA)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OfficialDocument)) == 0
    assert archive.client.list_objects_v2(Bucket=archive.bucket)["KeyCount"] == 0


async def test_concurrent_registration_creates_one_document(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
) -> None:
    path = tmp_path / "race.pdf"
    path.write_bytes(PDF)
    catalogue = DocumentCatalogue(sessions, archive)
    results = await asyncio.gather(*(catalogue.register(path, METADATA) for _ in range(2)))
    assert sorted(r.created for r in results) == [False, True]
    assert results[0].document.id == results[1].document.id
    assert len(archive.client.list_object_versions(Bucket=archive.bucket)["Versions"]) == 1


async def test_retry_after_upload_failure_preserves_single_original(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "retry.pdf"
    path.write_bytes(PDF)
    catalogue = DocumentCatalogue(sessions, archive)
    put = archive.put

    def interrupted(*args: object, **kwargs: object) -> None:
        # Upload conclui, mas a conexão cai antes do catálogo confirmar a transação.
        Mock(wraps=put)(*args, **kwargs)
        raise RuntimeError("interrupção simulada")

    with monkeypatch.context() as patch:
        patch.setattr(archive, "put", interrupted)
        with pytest.raises(RuntimeError, match="interrupção"):
            await catalogue.register(path, METADATA)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OfficialDocument)) == 0
        assert await session.scalar(select(func.count()).select_from(RawObject)) == 0
    assert (await catalogue.register(path, METADATA)).created
    assert len(archive.client.list_object_versions(Bucket=archive.bucket)["Versions"]) == 1


async def test_migration_and_real_cli(tmp_path: Path) -> None:
    url, s3 = os.getenv("TEST_DATABASE_URL"), os.getenv("TEST_S3_ENDPOINT_URL")
    if not url or not s3:
        pytest.skip("requer PostgreSQL e S3 de testes")
    name = "test_documents_" + uuid4().hex
    target_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_async_engine(target_url)
    storage = S3Archive(
        "test-doc-cli-" + uuid4().hex, endpoint=s3, access_key="test", secret_key="test"
    )
    storage.initialize()
    try:
        await alembic(target_url, "upgrade", "20261119_0006")
        await alembic(target_url, "upgrade", "head")
        await alembic(target_url, "check")
        path, meta = tmp_path / "original.pdf", tmp_path / "metadata.json"
        path.write_bytes(PDF)
        meta.write_text(METADATA.model_dump_json(), encoding="utf-8-sig")
        for expected in (True, False):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "api.documents",
                "register",
                "--file",
                str(path),
                "--metadata",
                str(meta),
                cwd=Path(__file__).resolve().parents[3],
                env={
                    **os.environ,
                    "DATABASE_URL": target_url,
                    "S3_ENDPOINT_URL": s3,
                    "S3_ACCESS_KEY": "test",
                    "S3_SECRET_KEY": "test",
                    "S3_BUCKET": storage.bucket,
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60)
            assert process.returncode == 0, "CLI falhou; saída privada omitida"
            assert RegistrationResult.model_validate_json(stdout).created is expected
        meta.write_text(json.dumps({"title": "inválido"}), encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "api.documents",
            "register",
            "--file",
            str(path),
            "--metadata",
            str(meta),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, error = await process.communicate()
        assert process.returncode == 1 and b"source" in error
        await alembic(target_url, "downgrade", "20261119_0006")
        await alembic(target_url, "upgrade", "head")
        await alembic(target_url, "check")
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
