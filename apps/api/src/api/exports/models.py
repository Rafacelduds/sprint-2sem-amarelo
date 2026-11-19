from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class DailyExport(Base):
    __tablename__ = "daily_raw_exports"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    reference: Mapped[dict[str, Any]] = mapped_column(JSONB)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signature: Mapped[str]
    snapshots: Mapped[int]
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
