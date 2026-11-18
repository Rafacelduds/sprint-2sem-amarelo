import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import IO
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.backup.models import BackupEntry, BackupReceipt, BackupRun, RecoveryManifest
from api.backup.postgres import postgres_tool
from api.collection.models import CollectionSnapshot
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.models import ProcessingRun, RawObject
from api.storage.s3 import S3Archive

logger = logging.getLogger(__name__)


class BackupService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        primary: S3Archive,
        backup: S3Archive,
        database_url: str,
    ):
        if primary.bucket == backup.bucket:
            raise ValueError("backup exige bucket separado")
        self.sessions = sessions
        self.primary = primary
        self.backup = backup
        self.database_url = database_url

    async def create(self, code_version: str) -> ObjectRef:
        started_at = datetime.now(UTC)
        backup_id = uuid4()
        with TemporaryDirectory(prefix="amarelo-backup-") as temporary:
            dump = Path(temporary) / "database.dump"
            await asyncio.to_thread(postgres_tool, "pg_dump", self.database_url, dump)
            dump_ref = await asyncio.to_thread(
                self.backup.put, dump, f"backups/database/{backup_id}.dump"
            )
            # Listagem após o snapshot do dump; tabelas do catálogo são append-only.
            refs: dict[str, ObjectRef] = {}
            catalog_identities: set[str] = set()
            for prefix in ("raw/", "derived/", "manifests/"):
                items = await asyncio.to_thread(list, self.primary.objects(prefix))
                refs.update((S3Archive.identity(ref), ref) for ref in items)
            async with self.sessions() as session:
                revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                for raw in (await session.scalars(select(RawObject))).all():
                    ref = ObjectRef.model_validate(raw.reference)
                    identity = S3Archive.identity(ref)
                    refs[identity] = ref
                    catalog_identities.add(identity)
                for run in (await session.scalars(select(ProcessingRun))).all():
                    manifest = ProcessingManifest.model_validate(run.manifest)
                    for ref in (
                        manifest.inputs
                        + manifest.outputs
                        + [ObjectRef.model_validate(run.reference)]
                    ):
                        refs[S3Archive.identity(ref)] = ref
            entries: list[BackupEntry] = []
            copies: dict[str, tuple[ObjectRef, ObjectRef]] = {}
            for ref in refs.values():
                if previous := copies.get(ref.key):
                    first, copied = previous
                    if first.model_dump(exclude={"bucket", "version_id"}) != ref.model_dump(
                        exclude={"bucket", "version_id"}
                    ):
                        raise ValueError("mesma chave com conteúdo ou metadados divergentes")
                else:
                    copied = await asyncio.to_thread(self.backup.replicate, self.primary, ref)
                    copies[ref.key] = (ref, copied)
                entries.append(BackupEntry(primary=ref, backup=copied))
            manifest = RecoveryManifest(
                backup_id=backup_id,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                code_version=code_version,
                database_revision=str(revision),
                database_dump=dump_ref,
                objects=entries,
            )
            path = Path(temporary) / "recovery.json"
            path.write_text(manifest.model_dump_json(), encoding="utf-8")
            result = await asyncio.to_thread(
                self.backup.put,
                path,
                f"backups/runs/{backup_id}.json",
                content_type="application/json",
            )
        async with self.sessions.begin() as session:
            session.add(
                BackupRun(
                    id=backup_id,
                    completed_at=manifest.completed_at,
                    reference=result.model_dump(mode="json"),
                    dump_reference=dump_ref.model_dump(mode="json"),
                )
            )
            await session.flush()
            for entry in entries:
                # O recibo de limpeza deve manter a identidade exata do catálogo,
                # e não um alias físico encontrado em um processamento posterior.
                if S3Archive.identity(entry.primary) not in catalog_identities:
                    continue
                values = dict(
                    key=entry.primary.key,
                    backup_id=backup_id,
                    primary_reference=entry.primary.model_dump(mode="json"),
                    backup_reference=entry.backup.model_dump(mode="json"),
                )
                statement = insert(BackupReceipt).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[BackupReceipt.key],
                        set_=values,
                    )
                )
        logger.info("backup_completed id=%s objects=%s", backup_id, len(entries))
        await self.clean_inbox()
        await self.retain_seven()
        return result

    async def clean_inbox(self) -> int:
        count = 0
        while True:
            async with self.sessions() as session:
                rows = (
                    await session.execute(
                        select(RawObject, BackupReceipt)
                        .join(BackupReceipt, BackupReceipt.key == RawObject.key)
                        .join(BackupRun, BackupRun.id == BackupReceipt.backup_id)
                        .join(CollectionSnapshot, CollectionSnapshot.id == RawObject.snapshot_id)
                        .where(CollectionSnapshot.body.is_not(None), BackupRun.expired_at.is_(None))
                        .limit(10)
                    )
                ).all()
            if not rows:
                return count
            for raw, receipt in rows:
                primary = ObjectRef.model_validate(receipt.primary_reference)
                secondary = ObjectRef.model_validate(receipt.backup_reference)
                if raw.reference != primary.model_dump(mode="json"):
                    raise ValueError("recibo divergente do catálogo")
                await asyncio.to_thread(self.primary.verify, primary)
                await asyncio.to_thread(self.backup.verify, secondary)
                async with self.sessions.begin() as session:
                    await session.execute(
                        update(CollectionSnapshot)
                        .where(CollectionSnapshot.id == raw.snapshot_id)
                        .values(body=None, body_purged_at=datetime.now(UTC))
                    )
                count += 1

    async def retain_seven(self) -> None:
        async with self.sessions() as session:
            expired = (
                await session.scalars(
                    select(BackupRun)
                    .where(BackupRun.expired_at.is_(None))
                    .order_by(BackupRun.completed_at.desc())
                    .offset(7)
                )
            ).all()
        for run in expired:
            # Apenas dump e manifesto desse ponto; nunca excluir brutos nem suas versões.
            for record in (run.dump_reference, run.reference):
                ref = ObjectRef.model_validate(record)
                if not ref.key.startswith(("backups/database/", "backups/runs/")):
                    raise ValueError("retenção fora do namespace de backup")
                options = {"Bucket": self.backup.bucket, "Key": ref.key}
                if ref.version_id:
                    options["VersionId"] = ref.version_id
                await asyncio.to_thread(self.backup.client.delete_object, **options)
            async with self.sessions.begin() as session:
                await session.execute(
                    update(BackupRun)
                    .where(BackupRun.id == run.id)
                    .values(expired_at=datetime.now(UTC))
                )


async def restore(
    backup: S3Archive,
    recovery_ref: ObjectRef,
    target: S3Archive,
    target_engine: AsyncEngine,
    target_url: str,
    map_path: Path,
) -> dict[str, int | str]:
    if backup.bucket == target.bucket:
        raise ValueError("destino de restauração deve ser separado")
    if map_path.exists():
        raise ValueError("mapa de restauração já existe")
    map_path.parent.mkdir(parents=True, exist_ok=True)
    # Reserva exclusiva antes de acessar os destinos. Nunca substituir um mapa prévio.
    with map_path.open("x", encoding="utf-8"):
        pass
    staged: Path | None = None
    published = False
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=map_path.parent,
            prefix=".restore-map-",
            delete=False,
        ) as output:
            staged = Path(output.name)
            result = await _restore_reserved(
                backup, recovery_ref, target, target_engine, target_url, output.file
            )
        os.replace(staged, map_path)
        published = True
        return result
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
        if not published:
            map_path.unlink(missing_ok=True)


async def _restore_reserved(
    backup: S3Archive,
    recovery_ref: ObjectRef,
    target: S3Archive,
    target_engine: AsyncEngine,
    target_url: str,
    map_output: IO[str],
) -> dict[str, int | str]:
    async with target_engine.connect() as connection:
        tables = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
            )
        )
        if tables:
            raise ValueError("banco de destino não está vazio")
    history = target.client.list_object_versions(Bucket=target.bucket, MaxKeys=1)
    if history.get("Versions") or history.get("DeleteMarkers"):
        raise ValueError("bucket de destino não está vazio")
    started = datetime.now(UTC)
    with TemporaryDirectory(prefix="amarelo-restore-") as temporary:
        path = Path(temporary) / "recovery"
        await asyncio.to_thread(backup.download, recovery_ref, path)
        manifest = RecoveryManifest.model_validate_json(path.read_bytes())
        dump = Path(temporary) / "database.dump"
        await asyncio.to_thread(backup.download, manifest.database_dump, dump)
        relocated: dict[str, ObjectRef] = {}
        copies: dict[str, ObjectRef] = {}
        for entry in manifest.objects:
            identity = S3Archive.identity(entry.backup)
            if identity not in copies:
                copies[identity] = await asyncio.to_thread(target.replicate, backup, entry.backup)
            copied = copies[identity]
            relocated[S3Archive.identity(entry.primary)] = copied
        target.relocations = relocated
        for entry in manifest.objects:
            await asyncio.to_thread(target.verify, entry.primary)
        # Materializar e sincronizar o mapa antes de modificar o banco.
        json.dump({key: ref.model_dump(mode="json") for key, ref in relocated.items()}, map_output)
        map_output.flush()
        os.fsync(map_output.fileno())
        await asyncio.to_thread(postgres_tool, "pg_restore", target_url, dump)
        async with target_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != manifest.database_revision:
                raise ValueError("revisão do banco restaurado diverge")
    return {
        "backup_id": str(manifest.backup_id),
        "objects": len(manifest.objects),
        "elapsed_seconds": int((datetime.now(UTC) - started).total_seconds()),
        "code_version": manifest.code_version,
    }
