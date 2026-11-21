from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.storage.contracts import ObjectRef


class BackupEntry(BaseModel):
    primary: ObjectRef
    backup: ObjectRef


class RecoveryManifest(BaseModel):
    backup_id: UUID
    started_at: datetime
    completed_at: datetime
    code_version: str = Field(pattern=r"^[0-9a-f]{40}$")
    database_revision: str
    database_dump: ObjectRef
    objects: list[BackupEntry]


class BackupRun(Base):
    __tablename__ = "backup_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dump_reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupReceipt(Base):
    __tablename__ = "backup_receipts"
    key: Mapped[str] = mapped_column(primary_key=True)
    backup_id: Mapped[UUID] = mapped_column(ForeignKey("backup_runs.id"))
    primary_reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
    backup_reference: Mapped[dict[str, Any]] = mapped_column(JSONB)


class BackupWorker(Base):
    __tablename__ = "backup_worker"
    id: Mapped[str] = mapped_column(primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupAttempt(Base):
    __tablename__ = "backup_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str]
    backup_id: Mapped[UUID | None] = mapped_column(ForeignKey("backup_runs.id"))
