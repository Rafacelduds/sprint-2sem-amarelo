from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class DailyReport(Base):
    __tablename__ = "daily_reliability_reports"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Gap(BaseModel):
    start: datetime
    end: datetime
    cause: Literal[
        "origin_failure",
        "storage_failure",
        "interrupted",
        "unfinished_cycle",
        "unknown_cycle_status",
        "no_cycle_record",
    ]
    evidence: Literal["recorded_cycle", "inferred_absence"]
    possible_maintenance: bool = False
    maintenance_confirmed: Literal[False] = False


class GtfsPeriod(BaseModel):
    start: datetime
    end: datetime
    sha256: str | None


class UsedVersion(BaseModel):
    sha256: str | None
    link_status: str
    observations: int


class ScheduleReference(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    manifest_sha256: str
    source_hashes: list[str]
    complete: bool
    has_discrepancies: bool


class ReliabilityReport(BaseModel):
    day: date
    timezone: Literal["America/Sao_Paulo"] = "America/Sao_Paulo"
    rule_version: Literal["us13-v1"] = "us13-v1"
    code_version: str = Field(default="working-tree", pattern=r"^(working-tree|[0-9a-f]{40})$")
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    provisional: bool
    fallback_interval_seconds: int = Field(ge=15, le=60)
    scheduling_tolerance_seconds: int = 5
    cycles: int
    legacy_interval_cycles: int
    gaps: list[Gap]
    gap_seconds: float
    gtfs_source_id: str
    gtfs_reference_periods: list[GtfsPeriod]
    gtfs_used: list[UsedVersion]
    schedule_references: list[ScheduleReference]
    schedules_status: Literal["references_found", "no_manifest_for_day"]
    limitations: list[str]
