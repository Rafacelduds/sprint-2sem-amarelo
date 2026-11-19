import asyncio
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTask

from api.config import get_settings
from api.db.session import SessionFactory
from api.exports.contract import DICTIONARY, LICENSE, SOURCE, ZONE, deadline
from api.exports.models import DailyExport
from api.storage.__main__ import archive_from_settings
from api.storage.contracts import ObjectRef

router = APIRouter(prefix="/exports/raw", tags=["dados abertos"])


def get_sessions() -> async_sessionmaker[AsyncSession]:
    return SessionFactory


Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)]


class ExportInfo(BaseModel):
    dia: date
    publicado_em: datetime
    prazo: datetime
    publicado_no_prazo: bool
    capturas: int
    bytes: int
    sha256: str
    download: str
    licenca: str = LICENSE
    fonte: str = SOURCE
    fuso: str = str(ZONE)
    cobertura: str = "Capturas disponíveis; não comprova coleta completa ou ausência de serviço."


def info(row: DailyExport) -> ExportInfo:
    ref = ObjectRef.model_validate(row.reference)
    return ExportInfo(
        dia=row.day,
        publicado_em=row.published_at,
        prazo=deadline(row.day),
        publicado_no_prazo=row.published_at <= deadline(row.day),
        capturas=row.snapshots,
        bytes=ref.size,
        sha256=ref.sha256,
        download=f"/exports/raw/{row.day}/download",
    )


@router.get("/dictionary", response_model=dict[str, str])
async def dictionary() -> dict[str, str]:
    """Dicionário da versão raw-responses-parquet-v1, também incluído no arquivo."""
    return DICTIONARY


@router.get("", response_model=list[ExportInfo])
async def catalog(
    sessions: Sessions,
    before: date | None = None,
    limit: Annotated[int, Query(ge=1, le=366)] = 31,
) -> list[ExportInfo]:
    """Dias publicados, mais recentes primeiro; paginação por before (exclusivo)."""
    statement = select(DailyExport).order_by(DailyExport.day.desc()).limit(limit)
    if before is not None:
        statement = statement.where(DailyExport.day < before)
    async with sessions() as session:
        return [info(row) for row in (await session.scalars(statement)).all()]


async def lookup(sessions: async_sessionmaker[AsyncSession], day: date) -> DailyExport:
    async with sessions() as session:
        row = await session.get(DailyExport, day)
    if row is None:
        raise HTTPException(404, "Nenhum arquivo publicado para este dia; consulte o catálogo.")
    return row


@router.get("/{day}", response_model=ExportInfo)
async def detail(day: date, sessions: Sessions) -> ExportInfo:
    return info(await lookup(sessions, day))


@router.get(
    "/{day}/download",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/vnd.apache.parquet": {}}},
        404: {"description": "Dia sem publicação"},
        503: {"description": "Arquivo temporariamente indisponível"},
    },
)
async def download(day: date, sessions: Sessions) -> FileResponse:
    """Baixa o Parquet publicado; confere o hash antes de enviar qualquer byte."""
    row = await lookup(sessions, day)
    temporary = TemporaryDirectory(prefix="amarelo-public-download-")
    path = Path(temporary.name) / "brutos.parquet"
    try:
        archive = archive_from_settings(get_settings())
        ref = ObjectRef.model_validate(row.reference)
        await asyncio.to_thread(archive.download, ref, path)
    except Exception:
        temporary.cleanup()
        raise HTTPException(503, "Arquivo indisponível; tente novamente mais tarde.") from None
    return FileResponse(
        path,
        media_type="application/vnd.apache.parquet",
        filename=f"brutos-{day}.parquet",
        headers={"ETag": f'"{ref.sha256}"', "Link": f'<{LICENSE}>; rel="license"'},
        background=BackgroundTask(temporary.cleanup),
    )
