"""Consulta restrita de ciclos persistidos; não consulta a SPTrans."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.backup.routes import authorize, get_sessions
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition

router = APIRouter(prefix="/operations/collection", tags=["operação"])


class CycleView(BaseModel):
    id: UUID
    scheduled_at: datetime
    finished_at: datetime | None
    status: str
    snapshots: int
    positions: int
    collected_at: datetime | None


class CollectionStatus(BaseModel):
    checked_at: datetime
    recent_activity: bool
    age_seconds: float | None
    activity_timeout_seconds: int
    last_success_at: datetime | None
    cycles: list[CycleView]


@router.get("", response_model=CollectionStatus, dependencies=[Depends(authorize)])
async def collection_status(
    response: Response,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
) -> CollectionStatus:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(UTC)
    async with sessions() as session:
        cycles = list(
            (
                await session.scalars(
                    select(CollectionCycle).order_by(CollectionCycle.scheduled_at.desc()).limit(20)
                )
            ).all()
        )
        views: list[CycleView] = []
        for cycle in cycles:
            snapshots, captured = (
                await session.execute(
                    select(func.count(), func.max(CollectionSnapshot.collected_at)).where(
                        CollectionSnapshot.cycle_id == cycle.id
                    )
                )
            ).one()
            positions = await session.scalar(
                select(func.count())
                .select_from(VehiclePosition)
                .join(CollectionSnapshot, VehiclePosition.snapshot_id == CollectionSnapshot.id)
                .where(CollectionSnapshot.cycle_id == cycle.id)
            )
            views.append(
                CycleView(
                    id=cycle.id,
                    scheduled_at=cycle.scheduled_at,
                    finished_at=cycle.finished_at,
                    status=cycle.status,
                    snapshots=snapshots,
                    positions=positions or 0,
                    collected_at=captured,
                )
            )
        last_success = await session.scalar(
            select(func.max(CollectionCycle.finished_at)).where(CollectionCycle.status == "success")
        )
    latest = cycles[0] if cycles else None
    timeout = max(120, (latest.interval_seconds or 60) * 3) if latest else 180
    activity = max(filter(None, (latest.scheduled_at, latest.finished_at))) if latest else None
    age = (now - activity).total_seconds() if activity else None
    return CollectionStatus(
        checked_at=now,
        recent_activity=age is not None and 0 <= age <= timeout,
        age_seconds=age,
        activity_timeout_seconds=timeout,
        last_success_at=last_success,
        cycles=views,
    )
