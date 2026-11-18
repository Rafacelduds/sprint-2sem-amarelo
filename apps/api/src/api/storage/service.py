import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.collection.models import CollectionSnapshot
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.models import ProcessingRun, RawObject
from api.storage.s3 import S3Archive, digest


@asynccontextmanager
async def exclusive(engine: AsyncEngine, key: int):
    async with engine.connect() as connection:
        if not await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
            raise RuntimeError("processo já está em execução")
        try:
            yield connection
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


class ArchiveService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], archive: S3Archive):
        self.sessions = sessions
        self.archive = archive

    async def register(self, ref: ObjectRef, identity: UUID, snapshot_id: UUID | None) -> None:
        async with self.sessions.begin() as session:
            previous = await session.get(RawObject, identity)
            if previous is not None:
                if previous.reference != ref.model_dump(mode="json"):
                    raise ValueError("catálogo divergente")
                return
            session.add(
                RawObject(
                    id=identity,
                    snapshot_id=snapshot_id,
                    key=ref.key,
                    reference=ref.model_dump(mode="json"),
                    archived_at=datetime.now(UTC),
                )
            )

    async def archive_pending(self, limit: int = 10) -> int:
        async with self.sessions() as session:
            snapshots = (
                await session.scalars(
                    select(CollectionSnapshot)
                    .outerjoin(RawObject, RawObject.snapshot_id == CollectionSnapshot.id)
                    .where(RawObject.id.is_(None))
                    .order_by(CollectionSnapshot.collected_at, CollectionSnapshot.id)
                    .limit(limit)
                )
            ).all()
        for snapshot in snapshots:
            if snapshot.body is None:
                raise ValueError("inbox sem bytes e sem referência arquivada")
            day = snapshot.collected_at.astimezone(UTC).strftime("%Y-%m-%d")
            endpoint = "posicao" if snapshot.company is None else f"garagem/{snapshot.company}"
            key = f"raw/olho-vivo/{endpoint}/{day}/{snapshot.id}.json.gz"
            with TemporaryDirectory(prefix="amarelo-inbox-") as temporary:
                path = Path(temporary) / "response.json"
                path.write_bytes(snapshot.body)
                ref = await asyncio.to_thread(
                    self.archive.put,
                    path,
                    key,
                    compress=True,
                    content_type="application/json",
                    metadata={
                        "source": "olho-vivo",
                        "endpoint": snapshot.endpoint,
                        "captured-at": snapshot.collected_at.isoformat(),
                        "snapshot-id": str(snapshot.id),
                        "cycle-id": str(snapshot.cycle_id),
                    },
                    resume=True,
                )
            await self.register(ref, snapshot.id, snapshot.id)
        return len(snapshots)

    async def import_file(self, path: Path, dataset: str) -> ObjectRef:
        if not dataset or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in dataset):
            raise ValueError("dataset deve usar letras minúsculas, números, - ou _")
        checksum, _ = await asyncio.to_thread(digest, path)
        key = f"raw/received/{dataset}/{checksum}/{path.name}"
        identity = uuid5(NAMESPACE_URL, key)
        async with self.sessions() as session:
            previous = await session.get(RawObject, identity)
            if previous:
                ref = ObjectRef.model_validate(previous.reference)
                await asyncio.to_thread(self.archive.verify, ref)
                return ref
        # Data de importação é observada; não representa a captura histórica.
        metadata = {"source": dataset}
        ref = await asyncio.to_thread(self.archive.put, path, key, metadata=metadata, resume=True)
        await self.register(ref, identity, None)
        return ref

    async def record(self, manifest: ProcessingManifest) -> ObjectRef:
        for ref in manifest.inputs + manifest.outputs:
            await asyncio.to_thread(self.archive.verify, ref)
        key = f"manifests/{manifest.run_id}.json"
        with TemporaryDirectory(prefix="amarelo-manifest-") as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(
                json.dumps(manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            ref = await asyncio.to_thread(
                self.archive.put, path, key, content_type="application/json", resume=True
            )
        async with self.sessions.begin() as session:
            previous = await session.get(ProcessingRun, manifest.run_id)
            if previous:
                if previous.manifest != manifest.model_dump(mode="json"):
                    raise ValueError("execução já registrada com outro conteúdo")
            else:
                session.add(
                    ProcessingRun(
                        id=manifest.run_id,
                        manifest=manifest.model_dump(mode="json"),
                        reference=ref.model_dump(mode="json"),
                    )
                )
        return ref
