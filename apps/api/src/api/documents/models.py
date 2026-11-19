from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class OfficialDocument(Base):
    __tablename__ = "official_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('contrato', 'aditivo', 'procedimento', 'ficha_indicador')",
            name="ck_official_documents_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    raw_object_id: Mapped[UUID] = mapped_column(ForeignKey("raw_objects.id"), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str | None] = mapped_column(String(300))
    document_type: Mapped[str] = mapped_column(String(30), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(2000))
    notes: Mapped[str | None] = mapped_column(String(4000))
    original_filename: Mapped[str] = mapped_column(String())
    catalogued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
