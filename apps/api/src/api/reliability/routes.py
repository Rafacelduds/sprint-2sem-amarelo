import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from api.reliability.models import DailyReport, ReliabilityReport

router = APIRouter(prefix="/reports/reliability", tags=["reliability"])
logger = logging.getLogger(__name__)


@router.get(
    "/{day}",
    response_model=ReliabilityReport,
    responses={
        404: {"description": "Dia ainda não publicado"},
        503: {"description": "Banco temporariamente indisponível"},
    },
)
async def daily_reliability(day: date) -> ReliabilityReport:
    from api.db.session import SessionFactory

    try:
        async with asyncio.timeout(5), SessionFactory() as session:
            row = await session.get(DailyReport, day)
            if row is None:
                raise HTTPException(404, "Relatório ainda não publicado para o dia")
            return ReliabilityReport.model_validate(row.document)
    except (SQLAlchemyError, TimeoutError):
        logger.warning("reliability_report_database_unavailable")
        raise HTTPException(503, "Relatório temporariamente indisponível") from None
