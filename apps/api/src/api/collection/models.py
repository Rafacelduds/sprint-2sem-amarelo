"""Modelo operacional; armazenamento imutável S3 é responsabilidade da US12."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class CollectionCycle(Base):
    __tablename__ = "collection_cycles"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str]
    error_code: Mapped[str | None]
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CollectionSnapshot(Base):
    __tablename__ = "collection_snapshots"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("collection_cycles.id"), index=True)
    endpoint: Mapped[str]
    company: Mapped[int | None]
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Inbox transacional de integração: bytes recebidos, antes de qualquer normalização.
    body: Mapped[bytes] = mapped_column(LargeBinary)


class VehiclePosition(Base):
    __tablename__ = "vehicle_positions"
    __table_args__ = (UniqueConstraint("prefix", "gps_at", name="uq_position_prefix_gps"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("collection_snapshots.id"))
    prefix: Mapped[str | None]
    line: Mapped[str | None]
    line_code: Mapped[int | None]
    direction: Mapped[int | None]
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    gps_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    in_garage: Mapped[bool]
    gtfs_version_sha256: Mapped[str | None] = mapped_column(ForeignKey("gtfs_versions.sha256"))
    gtfs_link_status: Mapped[str] = mapped_column(default="not_evaluated")
