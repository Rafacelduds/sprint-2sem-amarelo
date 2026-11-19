from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from api.storage.contracts import ObjectRef

DocumentType = Literal["contrato", "aditivo", "procedimento", "ficha_indicador"]
DateField = Literal["document_date", "catalogued_at"]


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=500)
    agency: str | None = Field(default=None, min_length=1, max_length=300)
    document_type: DocumentType
    document_date: date | None = None
    source: str = Field(min_length=1, max_length=2000)
    notes: str | None = Field(default=None, min_length=1, max_length=4000)


class CataloguedDocument(DocumentMetadata):
    id: UUID
    catalogued_at: datetime
    original_filename: str
    original: ObjectRef


class RegistrationResult(BaseModel):
    created: bool
    document: CataloguedDocument


class DocumentView(DocumentMetadata):
    id: UUID
    catalogued_at: datetime
    original_filename: str
    sha256: str
    size: int
    pdf_url: str


class DocumentPage(BaseModel):
    items: list[DocumentView]
    total: int
    limit: int
    offset: int
