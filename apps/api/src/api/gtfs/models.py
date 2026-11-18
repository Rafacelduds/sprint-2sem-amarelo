from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class GtfsVersion(Base):
    __tablename__ = "gtfs_versions"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int]
    bucket: Mapped[str]
    object_key: Mapped[str]
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    coverage_basis: Mapped[str]
    publisher_version: Mapped[str | None]


class GtfsCapture(Base):
    __tablename__ = "gtfs_captures"
    __table_args__ = (Index("ix_gtfs_captures_source_captured", "source_id", "captured_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    source_id: Mapped[str]
    source_url: Mapped[str]
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version_sha256: Mapped[str] = mapped_column(ForeignKey("gtfs_versions.sha256"))
