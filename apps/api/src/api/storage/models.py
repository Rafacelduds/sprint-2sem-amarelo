from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class RawObject(Base):
    __tablename__ = "raw_objects"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("collection_snapshots.id"), unique=True
    )
    key: Mapped[str] = mapped_column(unique=True)
    reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
