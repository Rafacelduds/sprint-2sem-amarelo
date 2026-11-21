from datetime import UTC, datetime, timedelta
from secrets import compare_digest
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.backup.models import BackupAttempt, BackupRun, BackupWorker
from api.backup.monitor import STALE_SECONDS, backup_due, cutoff
from api.config import get_settings
from api.db.session import SessionFactory

router = APIRouter(prefix="/operations/backups", tags=["operação"])
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    expected = get_settings().operations_token.get_secret_value()
    if (
        not expected
        or credentials is None
        or not compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        raise HTTPException(
            401,
            "Acesso de operação não autorizado.",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )


def get_sessions() -> async_sessionmaker[AsyncSession]:
    return SessionFactory


class AttemptView(BaseModel):
    id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "success", "failed", "unknown"]
    backup_id: UUID | None


class PointView(BaseModel):
    id: UUID
    completed_at: datetime
    expired_at: datetime | None
    manifest_sha256: str | None
    dump_sha256: str | None
    verified_at_creation: datetime | None


class BackupStatus(BaseModel):
    checked_at: datetime
    worker_active: bool
    heartbeat_at: datetime | None
    heartbeat_timeout_seconds: int = STALE_SECONDS
    schedule: str = "Diariamente às 03:00 UTC"
    next_execution: datetime | None
    overdue: bool
    last_success_at: datetime | None
    attempts: list[AttemptView]
    points: list[PointView]


@router.get("", response_model=BackupStatus, dependencies=[Depends(authorize)])
async def status(
    response: Response,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessions)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> BackupStatus:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(UTC)
    async with sessions() as session:
        worker = await session.get(BackupWorker, "daily")
        attempts = list(
            (
                await session.scalars(
                    select(BackupAttempt).order_by(BackupAttempt.started_at.desc()).limit(limit)
                )
            ).all()
        )
        runs = list(
            (
                await session.scalars(
                    select(BackupRun).order_by(BackupRun.completed_at.desc()).limit(limit)
                )
            ).all()
        )
        last_success = await session.scalar(
            select(BackupRun.completed_at)
            .where(BackupRun.expired_at.is_(None))
            .order_by(BackupRun.completed_at.desc())
            .limit(1)
        )
        verified = dict(
            (
                await session.execute(
                    select(BackupAttempt.backup_id, BackupAttempt.finished_at).where(
                        BackupAttempt.status == "success", BackupAttempt.backup_id.is_not(None)
                    )
                )
            ).all()
        )
    active = (
        worker is not None and 0 <= (now - worker.heartbeat_at).total_seconds() <= STALE_SECONDS
    )
    overdue = backup_due(last_success, now)
    next_execution = None
    if active:
        next_execution = (
            worker.retry_at
            if worker and worker.retry_at
            else (cutoff(now) if overdue else cutoff(now) + timedelta(days=1))
        )
    return BackupStatus(
        checked_at=now,
        worker_active=active,
        heartbeat_at=worker.heartbeat_at if worker else None,
        next_execution=next_execution,
        overdue=overdue,
        last_success_at=last_success,
        attempts=[
            AttemptView(
                id=a.id,
                started_at=a.started_at,
                finished_at=a.finished_at,
                status=a.status if a.status in ("running", "success", "failed") else "unknown",
                backup_id=a.backup_id,
            )
            for a in attempts
        ],
        points=[
            PointView(
                id=r.id,
                completed_at=r.completed_at,
                expired_at=r.expired_at,
                manifest_sha256=r.reference.get("sha256"),
                dump_sha256=r.dump_reference.get("sha256"),
                verified_at_creation=verified.get(r.id),
            )
            for r in runs
        ],
    )
