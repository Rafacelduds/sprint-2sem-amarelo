import asyncio
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from api.config import get_settings
from api.documents.contracts import DateField, DocumentPage, DocumentType, DocumentView
from api.documents.reader import DocumentReader
from api.storage.__main__ import archive_from_settings
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


def get_reader() -> DocumentReader:
    from api.db.session import SessionFactory

    return DocumentReader(SessionFactory)


def get_archive() -> S3Archive:
    try:
        return archive_from_settings(get_settings())
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "Arquivo temporariamente indisponível") from None


def download_directory() -> Iterator[Path]:
    # Dependência com yield mantém o arquivo até terminar a resposta e limpa também em erro.
    with TemporaryDirectory(prefix="amarelo-document-download-") as temporary:
        yield Path(temporary)


async def find_document(reader: DocumentReader, identity: UUID) -> tuple[DocumentView, ObjectRef]:
    try:
        async with asyncio.timeout(5):
            result = await reader.get(identity)
    except (SQLAlchemyError, TimeoutError, OSError, ValueError):
        logger.warning("document_catalogue_unavailable")
        raise HTTPException(503, "Acervo temporariamente indisponível") from None
    if result is None:
        raise HTTPException(404, "Documento não encontrado")
    return result


@router.get(
    "", response_model=DocumentPage, responses={503: {"description": "Catálogo indisponível"}}
)
async def search_documents(
    reader: Annotated[DocumentReader, Depends(get_reader)],
    document_type: DocumentType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: DateField = "document_date",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentPage:
    """Datas inclusivas; cadastro usa o dia civil de São Paulo. Nulos não casam com período."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(422, "date_from deve ser anterior ou igual a date_to")
    try:
        async with asyncio.timeout(5):
            return await reader.search(
                document_type=document_type,
                date_from=date_from,
                date_to=date_to,
                date_field=date_field,
                limit=limit,
                offset=offset,
            )
    except (SQLAlchemyError, TimeoutError, OSError, ValueError):
        logger.warning("document_catalogue_unavailable")
        raise HTTPException(503, "Acervo temporariamente indisponível") from None


@router.get(
    "/{identity}",
    response_model=DocumentView,
    responses={
        404: {"description": "Documento inexistente"},
        503: {"description": "Catálogo indisponível"},
    },
)
async def document_details(
    identity: UUID,
    reader: Annotated[DocumentReader, Depends(get_reader)],
) -> DocumentView:
    document, _ = await find_document(reader, identity)
    return document


@router.get(
    "/{identity}/pdf",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        404: {"description": "Documento inexistente"},
        503: {"description": "Original indisponível ou com falha de integridade"},
    },
)
async def document_pdf(
    identity: UUID,
    reader: Annotated[DocumentReader, Depends(get_reader)],
    archive: Annotated[S3Archive, Depends(get_archive)],
    directory: Annotated[Path, Depends(download_directory)],
) -> FileResponse:
    document, reference = await find_document(reader, identity)
    target = directory / "original.pdf"
    try:
        if reference.encoding != "identity" or reference.content_type != "application/pdf":
            raise ValueError("referência PDF inválida")
        # Download em disco e hash verificado antes de começar a enviar bytes ao navegador.
        await run_in_threadpool(archive.download, reference, target)
    except (BotoCoreError, ClientError, OSError, ValueError):
        logger.warning("document_original_unavailable")
        raise HTTPException(503, "Arquivo temporariamente indisponível") from None
    return FileResponse(
        target,
        media_type="application/pdf",
        filename=document.original_filename,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )
