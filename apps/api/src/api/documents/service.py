import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.documents.contracts import CataloguedDocument, DocumentMetadata, RegistrationResult
from api.documents.models import OfficialDocument
from api.storage.contracts import ObjectRef
from api.storage.models import RawObject
from api.storage.s3 import S3Archive, digest


def snapshot_pdf(source: Path, destination: Path) -> tuple[str, int]:
    # Snapshot temporário evita que alterações no arquivo durante o cadastro mudem o hash.
    with source.open("rb") as reader, destination.open("xb") as writer:
        if reader.read(5) != b"%PDF-":
            raise ValueError("arquivo sem assinatura PDF")
        reader.seek(0)
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
    with destination.open("rb") as reader:
        reader.seek(max(0, destination.stat().st_size - 1024))
        if b"%%EOF" not in reader.read():
            raise ValueError("PDF sem marcador final; confira se o arquivo está completo")
    return digest(destination)


def metadata_of(document: OfficialDocument) -> DocumentMetadata:
    return DocumentMetadata.model_validate(
        {name: getattr(document, name) for name in DocumentMetadata.model_fields}
    )


def record_of(document: OfficialDocument, reference: ObjectRef) -> CataloguedDocument:
    return CataloguedDocument(
        **metadata_of(document).model_dump(),
        id=document.id,
        catalogued_at=document.catalogued_at,
        original_filename=document.original_filename,
        original=reference,
    )


class DocumentCatalogue:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], archive: S3Archive):
        self.sessions = sessions
        self.archive = archive

    async def register(self, path: Path, metadata: DocumentMetadata) -> RegistrationResult:
        with TemporaryDirectory(prefix="amarelo-document-") as temporary:
            snapshot = Path(temporary) / "original.pdf"
            checksum, _ = await asyncio.to_thread(snapshot_pdf, path, snapshot)
            async with self.sessions.begin() as session:
                # Serializa o mesmo conteúdo entre CLIs concorrentes, não o catálogo inteiro.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": int(checksum[:15], 16)},
                )
                previous = await session.scalar(
                    select(OfficialDocument).where(OfficialDocument.sha256 == checksum)
                )
                if previous is not None:
                    if metadata_of(previous) != metadata:
                        raise ValueError(
                            "PDF já catalogado com metadados diferentes; nada foi alterado"
                        )
                    raw = await session.get(RawObject, previous.raw_object_id)
                    if raw is None:
                        raise ValueError("referência original ausente no catálogo técnico")
                    ref = ObjectRef.model_validate(raw.reference)
                    await asyncio.to_thread(self.archive.verify, ref)
                    return RegistrationResult(created=False, document=record_of(previous, ref))

                # O nome recebido fica no catálogo; identidade do objeto depende só dos bytes.
                key = f"raw/received/official-documents/{checksum}/original.pdf"
                ref = await asyncio.to_thread(
                    self.archive.put,
                    snapshot,
                    key,
                    content_type="application/pdf",
                    metadata={"source": "official-documents"},
                    resume=True,
                )
                identity = uuid5(NAMESPACE_URL, key)
                now = datetime.now(UTC)
                session.add(
                    RawObject(
                        id=identity,
                        snapshot_id=None,
                        key=key,
                        reference=ref.model_dump(mode="json"),
                        archived_at=now,
                    )
                )
                # Flush explicita a ordem de inserção da FK sem relacionamento ORM.
                await session.flush()
                document = OfficialDocument(
                    id=identity,
                    raw_object_id=identity,
                    sha256=checksum,
                    original_filename=path.name,
                    catalogued_at=now,
                    **metadata.model_dump(),
                )
                session.add(document)
                await session.flush()
                return RegistrationResult(created=True, document=record_of(document, ref))
