"""Resumo público da última coleta histórica, sem detalhes privados da operação."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.backup.routes import get_sessions
from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle

router = APIRouter(prefix="/collection", tags=["cobertura"])


class CoverageView(BaseModel):
    checked_at: datetime
    cycle_at: datetime | None
    status: Literal["complete", "partial", "unknown"]
    stale: bool
    failed_garage_companies: list[int]
    road_saved: bool | None
    garages_saved: int | None


def summarize(cycle: CollectionCycle | None, now: datetime) -> CoverageView:
    details = None
    if cycle and cycle.diagnostics:
        try:
            details = CycleDiagnostics.model_validate(cycle.diagnostics)
        except ValidationError:
            pass
    return CoverageView(
        checked_at=now,
        cycle_at=cycle.scheduled_at if cycle else None,
        status=("complete" if cycle.status == "success" else "partial") if cycle else "unknown",
        stale=cycle is None or not 0 <= (now - cycle.scheduled_at).total_seconds() <= 180,
        failed_garage_companies=sorted(
            {
                int(match[1])
                for key in (details.failures if details else {})
                if (match := re.fullmatch(r"company_(\d{1,12})", key))
            }
        ),
        road_saved=details.road_saved if details else None,
        garages_saved=details.garages_saved if details else None,
    )


@router.get("/coverage", response_model=CoverageView)
async def coverage(
    response: Response,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> CoverageView:
    response.headers["Cache-Control"] = "no-store"
    try:
        async with sessions() as session:
            cycle = await session.scalar(
                select(CollectionCycle)
                .where(CollectionCycle.finished_at.is_not(None))
                .order_by(CollectionCycle.scheduled_at.desc())
                .limit(1)
            )
    except (SQLAlchemyError, OSError):
        raise HTTPException(
            503, "Cobertura da coleta indisponível.", headers={"Cache-Control": "no-store"}
        ) from None
    return summarize(cycle, datetime.now(UTC))
