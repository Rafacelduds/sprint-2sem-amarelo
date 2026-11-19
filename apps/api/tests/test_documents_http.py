from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import gettempdir
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from api.documents.contracts import CataloguedDocument, DocumentMetadata
from api.documents.models import OfficialDocument
from api.documents.reader import DocumentReader
from api.documents.routes import get_archive, get_reader
from api.documents.service import DocumentCatalogue
from api.main import create_app
from api.storage.models import RawObject
from api.storage.s3 import S3Archive
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from test_collection_postgres import sessions as sessions  # noqa: F401
from test_storage import archive as archive  # noqa: F401

PDF = b"%PDF-1.4\n% preservacao HTTP\n%%EOF\n"


@pytest.fixture
async def documents(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    tmp_path: Path,
) -> list[CataloguedDocument]:
    catalogue = DocumentCatalogue(sessions, archive)
    records: list[CataloguedDocument] = []
    for i, day in enumerate([date(2021, 9, 1), date(2021, 9, 2), None]):
        path = tmp_path / f"ficha técnica {i}.pdf"
        path.write_bytes(PDF + f"% {i}\n".encode())
        result = await catalogue.register(
            path,
            DocumentMetadata(
                title=f"Documento {i}",
                agency=None,
                document_type="procedimento" if day is None else "ficha_indicador",
                document_date=day,
                source="Pasta de documentos recebidos do cliente",
            ),
        )
        records.append(result.document)
    # São Paulo: primeiro em 18/11 23h30, demais em 19/11 00h.
    async with sessions.begin() as session:
        for i, record in enumerate(records):
            document = await session.get(OfficialDocument, record.id)
            assert document is not None
            document.catalogued_at = datetime(
                2026, 11, 19, 2 if i == 0 else 3, 30 if i == 0 else 0, tzinfo=UTC
            )
    return records


@pytest.fixture
async def client(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_reader] = lambda: DocumentReader(sessions)
    app.dependency_overrides[get_archive] = lambda: archive
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as connection:
        yield connection


async def test_search_filters_null_dates_inclusive_bounds_and_pagination(
    client: httpx.AsyncClient,
    documents: list[CataloguedDocument],
) -> None:
    response = await client.get("/documents")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3 and len(page["items"]) == 3
    assert any(item["document_date"] is None for item in page["items"])
    assert all("original" not in item and "bucket" not in item for item in page["items"])
    response = await client.get(
        "/documents",
        params={
            "document_type": "ficha_indicador",
            "date_from": "2021-09-01",
            "date_to": "2021-09-01",
        },
    )
    assert [r["id"] for r in response.json()["items"]] == [str(documents[0].id)]
    response = await client.get("/documents", params={"date_from": "2021-09-02"})
    assert [r["id"] for r in response.json()["items"]] == [str(documents[1].id)]
    response = await client.get("/documents", params={"date_to": "2021-09-01"})
    assert response.json()["total"] == 1
    first = (await client.get("/documents", params={"limit": 1})).json()
    second = (await client.get("/documents", params={"limit": 1, "offset": 1})).json()
    assert first["total"] == second["total"] == 3
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (await client.get("/documents", params={"offset": 3})).json()["items"] == []
    assert (await client.get("/documents", params={"document_type": "contrato"})).json()[
        "total"
    ] == 0


async def test_catalogue_date_uses_sao_paulo_and_can_find_undated_document(
    client: httpx.AsyncClient,
    documents: list[CataloguedDocument],
) -> None:
    page = (
        await client.get(
            "/documents",
            params={
                "date_field": "catalogued_at",
                "date_from": "2026-11-19",
                "date_to": "2026-11-19",
            },
        )
    ).json()
    assert {r["id"] for r in page["items"]} == {str(r.id) for r in documents[1:]}
    assert any(r["document_date"] is None for r in page["items"])


@pytest.mark.parametrize(
    "query",
    [
        {"document_type": "desconhecido"},
        {"date_from": "ontem"},
        {"date_from": "2021-09-02", "date_to": "2021-09-01"},
        {"date_field": "invalido"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
async def test_invalid_search_is_422(
    client: httpx.AsyncClient, query: dict[str, str | int]
) -> None:
    assert (await client.get("/documents", params=query)).status_code == 422


async def test_details_and_original_preserve_pinned_version_and_clean_temporary_file(
    client: httpx.AsyncClient,
    documents: list[CataloguedDocument],
    archive: S3Archive,
) -> None:
    document = documents[0]
    response = await client.get(f"/documents/{document.id}")
    assert response.status_code == 200
    view = response.json()
    assert view["source"] == document.source and view["sha256"] == document.original.sha256
    assert "raw/" not in response.text and "version_id" not in response.text
    # Uma nova versão externa não pode substituir os bytes referenciados pelo catálogo.
    archive.client.put_object(Bucket=archive.bucket, Key=document.original.key, Body=b"changed")
    before = set(Path(gettempdir()).glob("amarelo-document-download-*"))
    response = await client.get(view["pdf_url"])
    assert response.status_code == 200 and response.content == PDF + b"% 0\n"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert set(Path(gettempdir()).glob("amarelo-document-download-*")) == before


async def test_integrity_failure_never_serves_pdf_and_cleans_temporary_file(
    client: httpx.AsyncClient,
    documents: list[CataloguedDocument],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    document = documents[0]
    async with sessions.begin() as session:
        row = await session.get(RawObject, document.id)
        assert row is not None
        row.reference = {**row.reference, "stored_sha256": "0" * 64}
    before = set(Path(gettempdir()).glob("amarelo-document-download-*"))
    response = await client.get(f"/documents/{document.id}/pdf")
    assert response.status_code == 503
    assert "raw/" not in response.text and "%PDF" not in response.text
    assert set(Path(gettempdir()).glob("amarelo-document-download-*")) == before


async def test_missing_original_is_503_not_a_missing_document(
    client: httpx.AsyncClient,
    documents: list[CataloguedDocument],
    archive: S3Archive,
) -> None:
    document = documents[0]
    archive.client.delete_object(
        Bucket=archive.bucket, Key=document.original.key, VersionId=document.original.version_id
    )
    assert (await client.get(f"/documents/{document.id}")).status_code == 200
    assert (await client.get(f"/documents/{document.id}/pdf")).status_code == 503


async def test_missing_and_malformed_ids(client: httpx.AsyncClient) -> None:
    for suffix in ("", "/pdf"):
        assert (await client.get(f"/documents/{uuid4()}{suffix}")).status_code == 404
        assert (await client.get(f"/documents/not-a-uuid{suffix}")).status_code == 422


async def test_empty_catalogue(client: httpx.AsyncClient) -> None:
    response = await client.get("/documents")
    assert response.status_code == 200 and response.json()["total"] == 0


async def test_unavailable_catalogue_does_not_leak_error_details() -> None:
    app = create_app()
    broken = DocumentReader(async_sessionmaker())
    broken.search = AsyncMock(side_effect=SQLAlchemyError("token=private"))
    broken.get = AsyncMock(side_effect=SQLAlchemyError("token=private"))
    app.dependency_overrides[get_reader] = lambda: broken
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        for path in ("/documents", f"/documents/{uuid4()}"):
            response = await c.get(path)
            assert response.status_code == 503 and "private" not in response.text


async def test_refused_database_connection_returns_503() -> None:
    engine = create_async_engine("postgresql+asyncpg://test:test@127.0.0.1:1/unavailable")
    app = create_app()
    app.dependency_overrides[get_reader] = lambda: DocumentReader(async_sessionmaker(engine))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("/documents", f"/documents/{uuid4()}"):
                response = await client.get(path)
                assert response.status_code == 503 and "127.0.0.1" not in response.text
    finally:
        await engine.dispose()
