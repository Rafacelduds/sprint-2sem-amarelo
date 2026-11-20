from datetime import date
from typing import Annotated, Any
from uuid import UUID

from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.config import get_settings
from api.schedules import query
from api.storage.__main__ import archive_from_settings
from api.storage.s3 import S3Archive

router = APIRouter(prefix="/schedules", tags=["programação"])


def get_archive() -> S3Archive:
    try:
        return archive_from_settings(
            get_settings(),
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 1},
            ),
        )
    except Exception:
        raise HTTPException(503, "Armazenamento temporariamente indisponível.") from None


Archive = Annotated[S3Archive, Depends(get_archive)]
ERRORS: dict[int | str, dict[str, Any]] = {
    503: {"description": "Publicação indisponível ou integridade não confirmada"}
}


@router.get("", response_model=query.ScheduleCatalog, responses=ERRORS)
def schedule_catalog(day: date, response: Response, archive: Archive) -> query.ScheduleCatalog:
    """Execuções publicadas no dia, mais recentes primeiro; vazio não significa zero serviço."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return query.catalog(archive, day)
    except Exception:
        raise HTTPException(
            503, "Não foi possível consultar as publicações de programação."
        ) from None


@router.get(
    "/{run_id}/departures",
    response_model=query.ScheduleDepartures,
    responses={**ERRORS, 404: {"description": "Execução ou linha não publicada"}},
)
def schedule_departures(
    run_id: UUID,
    response: Response,
    archive: Archive,
    line: Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9-]+$")],
    direction: Annotated[str | None, Query(pattern=r"^(0|1|unknown)$")] = None,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> query.ScheduleDepartures:
    """Parquet verificado, ordem original e multiplicidades preservadas; não dispara coleta."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return query.departures(archive, run_id, line, direction, offset, limit)
    except query.RunNotFound:
        raise HTTPException(404, "Execução não publicada.") from None
    except LookupError:
        raise HTTPException(404, "Linha não incluída nesta publicação.") from None
    except Exception:
        raise HTTPException(503, "Publicação indisponível; integridade não confirmada.") from None
