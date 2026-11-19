from datetime import date
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.documents.contracts import DateField, DocumentPage, DocumentType, DocumentView
from api.documents.models import OfficialDocument
from api.documents.service import metadata_of
from api.storage.contracts import ObjectRef
from api.storage.models import RawObject


def public_document(document: OfficialDocument, ref: ObjectRef) -> DocumentView:
    return DocumentView(
        **metadata_of(document).model_dump(),
        id=document.id,
        catalogued_at=document.catalogued_at,
        original_filename=document.original_filename,
        sha256=ref.sha256,
        size=ref.size,
        pdf_url=f"/documents/{document.id}/pdf",
    )


class DocumentReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def search(
        self,
        *,
        document_type: DocumentType | None,
        date_from: date | None,
        date_to: date | None,
        date_field: DateField,
        limit: int,
        offset: int,
    ) -> DocumentPage:
        query = select(OfficialDocument, RawObject).join(
            RawObject, RawObject.id == OfficialDocument.raw_object_id
        )
        if document_type is not None:
            query = query.where(OfficialDocument.document_type == document_type)
        day = (
            OfficialDocument.document_date
            if date_field == "document_date"
            else cast(func.timezone("America/Sao_Paulo", OfficialDocument.catalogued_at), Date)
        )
        if date_from is not None:
            query = query.where(day >= date_from)
        if date_to is not None:
            query = query.where(day <= date_to)
        async with self.sessions() as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = await session.execute(
                query.order_by(OfficialDocument.catalogued_at.desc(), OfficialDocument.id.desc())
                .limit(limit)
                .offset(offset)
            )
            items = [
                public_document(document, ObjectRef.model_validate(raw.reference))
                for document, raw in rows
            ]
        return DocumentPage(items=items, total=total or 0, limit=limit, offset=offset)

    async def get(self, identity: UUID) -> tuple[DocumentView, ObjectRef] | None:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(OfficialDocument, RawObject)
                    .join(RawObject, RawObject.id == OfficialDocument.raw_object_id)
                    .where(OfficialDocument.id == identity)
                )
            ).one_or_none()
            if row is None:
                return None
            document, raw = row
            reference = ObjectRef.model_validate(raw.reference)
            return public_document(document, reference), reference
