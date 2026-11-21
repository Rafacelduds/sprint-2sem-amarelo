"""Consulta restrita de ciclos persistidos; nÃ£o consulta a SPTrans."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.backup.routes import authorize, get_sessions
from api.collection.diagnostics import CycleDiagnostics
from api.collection.models import CollectionCycle, CollectionSnapshot, VehiclePosition
from api.collection.runner import CollectionSettings

router = APIRouter(prefix="/operations/collection", tags=["operaÃ§Ã£o"])


class CycleView(BaseModel):
    id: UUID
    scheduled_at: datetime
    finished_at: datetime | None
    status: str
    snapshots: int
    positions: int
    collected_at: datetime | None
    diagnostics: dict[str, str]
    failure_started_at: datetime | None
    recovered_at: datetime | None
    outage_seconds: float | None
    alert_delivered_at: datetime | None
    recovery_alert_delivered_at: datetime | None


class CollectionStatus(BaseModel):
    alert_configured_now: bool
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
            details: dict[str, str] = {}
            try:
                if cycle.diagnostics:
                    details = CycleDiagnostics.model_validate(cycle.diagnostics).sections()
            except ValidationError:
                pass
            started = recovered = None
            if cycle.status not in ("success", "running"):
                previous_success = await session.scalar(
                    select(func.max(CollectionCycle.scheduled_at)).where(
                        CollectionCycle.status == "success",
                        CollectionCycle.scheduled_at < cycle.scheduled_at,
                    )
                )
                failures = select(func.min(CollectionCycle.scheduled_at)).where(
                    CollectionCycle.status.not_in(("success", "running")),
                    CollectionCycle.scheduled_at <= cycle.scheduled_at,
                )
                if previous_success:
                    failures = failures.where(CollectionCycle.scheduled_at > previous_success)
                started = await session.scalar(failures)
                recovered = await session.scalar(
                    select(func.min(CollectionCycle.finished_at)).where(
                        CollectionCycle.status == "success",
                        CollectionCycle.scheduled_at > cycle.scheduled_at,
                    )
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
                    diagnostics=details,
                    failure_started_at=started,
                    recovered_at=recovered,
                    outage_seconds=max(0, ((recovered or now) - started).total_seconds())
                    if started
                    else None,
                    alert_delivered_at=cycle.alerted_at,
                    recovery_alert_delivered_at=cycle.recovery_alerted_at,
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
        alert_configured_now=CollectionSettings().collection_alert_webhook is not None,
        checked_at=now,
        recent_activity=age is not None and 0 <= age <= timeout,
        age_seconds=age,
        activity_timeout_seconds=timeout,
        last_success_at=last_success,
        cycles=views,
    )
