import asyncio
import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import UUID, uuid4

import duckdb
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from api.collection.models import CollectionSnapshot
from api.exports.contract import DICTIONARY, LICENSE, RULE, SOURCE, ZONE, bounds
from api.exports.models import DailyExport
from api.storage.contracts import ObjectRef, ProcessingManifest
from api.storage.models import RawObject
from api.storage.s3 import S3Archive
from api.storage.service import ArchiveService


class PendingArchive(RuntimeError):
    pass


@dataclass(frozen=True)
class Capture:
    id: UUID
    cycle_id: UUID
    collected_at: datetime
    endpoint: str
    company: int | None
    ref: ObjectRef


def build_parquet(captures: list[Capture], archive: S3Archive, day: date, path: Path) -> None:
    # Banco em disco e um corpo por vez: não materializar o dia inteiro em memória.
    with duckdb.connect(str(path.with_suffix(".duckdb"))) as connection:
        connection.execute("SET memory_limit='128MB'")
        connection.execute("SET threads=1")
        connection.execute("SET TimeZone='UTC'")
        connection.execute("SET preserve_insertion_order=true")
        connection.execute(
            "CREATE TABLE responses (captura_id VARCHAR, ciclo_id VARCHAR, "
            "coletado_em TIMESTAMPTZ, endpoint VARCHAR, empresa INTEGER, fonte VARCHAR, "
            "sha256_original VARCHAR, corpo_original BLOB)"
        )
        for capture in captures:
            downloaded = path.with_suffix(".payload")
            archive.download(capture.ref, downloaded)
            try:
                body = downloaded.read_bytes()
                if capture.ref.encoding == "gzip":
                    body = gzip.decompress(body)
                connection.execute(
                    "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        str(capture.id),
                        str(capture.cycle_id),
                        capture.collected_at,
                        capture.endpoint,
                        capture.company,
                        SOURCE,
                        capture.ref.sha256,
                        body,
                    ],
                )
            finally:
                downloaded.unlink(missing_ok=True)
        metadata = {
            "license": LICENSE,
            "license_name": "CC BY 4.0",
            "attribution": "SPTrans / API Olho Vivo; disponibilização pelo Grupo Amarelo",
            "source": SOURCE,
            "day": day.isoformat(),
            "timezone": str(ZONE),
            "schema_version": RULE,
            "data_dictionary": json.dumps(DICTIONARY, ensure_ascii=False, sort_keys=True),
        }

        # Literais escapados; nenhuma URL ou chave recebida vira código SQL.
        def literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        kv = ", ".join(literal(k) + ": " + literal(v) for k, v in metadata.items())
        connection.execute(
            f"COPY responses TO {literal(str(path))} "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 2048, KV_METADATA {{{kv}}})"
        )


class ExportService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], archive: S3Archive):
        self.sessions = sessions
        self.archive = archive

    async def candidates(self, today: date) -> list[date]:
        local_day = func.date(func.timezone(str(ZONE), CollectionSnapshot.collected_at))
        async with self.sessions() as session:
            rows = await session.execute(
                select(local_day, func.count(CollectionSnapshot.id))
                .where(CollectionSnapshot.collected_at < bounds(today)[0])
                .group_by(local_day)
                .order_by(local_day)
            )
            exports = {e.day: e for e in (await session.scalars(select(DailyExport))).all()}
            return [d for d, count in rows if d not in exports or exports[d].snapshots != count]

    async def publish(self, day: date, code_version: str) -> DailyExport | None:
        if day >= datetime.now(ZONE).date():
            raise ValueError("publicar apenas dias encerrados em America/Sao_Paulo")
        start, end = bounds(day)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(CollectionSnapshot, RawObject)
                    .options(defer(CollectionSnapshot.body))
                    .outerjoin(RawObject, RawObject.snapshot_id == CollectionSnapshot.id)
                    .where(
                        CollectionSnapshot.collected_at >= start,
                        CollectionSnapshot.collected_at < end,
                    )
                    .order_by(CollectionSnapshot.collected_at, CollectionSnapshot.id)
                )
            ).all()
            previous = await session.get(DailyExport, day)
        if not rows:
            return None  # Ausência de coleta não vira arquivo que promete cobertura.
        captures: list[Capture] = []
        for snapshot, maybe_raw in rows:
            raw = cast(RawObject | None, maybe_raw)
            if raw is None:
                raise PendingArchive("captura ainda não arquivada pela US12")
            ref = ObjectRef.model_validate(raw.reference)
            captures.append(
                Capture(
                    snapshot.id,
                    snapshot.cycle_id,
                    snapshot.collected_at,
                    snapshot.endpoint,
                    snapshot.company,
                    ref,
                )
            )
        signature = hashlib.sha256(
            json.dumps(
                {
                    "rule": RULE,
                    "code": code_version,
                    "captures": [[str(c.id), c.ref.model_dump(mode="json")] for c in captures],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if previous is not None and previous.signature == signature:
            await asyncio.to_thread(
                self.archive.verify, ObjectRef.model_validate(previous.reference)
            )
            return previous
        # Validar versão antes de escrever objetos; manifesto completo após o Parquet.
        if len(code_version) != 40 or any(c not in "0123456789abcdef" for c in code_version):
            raise ValueError("code-version exige commit Git completo")
        with TemporaryDirectory(prefix="amarelo-export-") as temporary:
            path = Path(temporary) / "brutos.parquet"
            await asyncio.to_thread(build_parquet, captures, self.archive, day, path)
            output = await asyncio.to_thread(
                self.archive.put,
                path,
                f"derived/public-raw/{day}/{signature}.parquet",
                content_type="application/vnd.apache.parquet",
                resume=True,
                metadata={"source": SOURCE, "license": LICENSE, "schema-version": RULE},
            )
        manifest = ProcessingManifest(
            run_id=uuid4(),
            dataset="public-raw",
            period_start=start,
            period_end=end,
            code_version=code_version,
            rule_version=RULE,
            inputs=[capture.ref for capture in captures],
            outputs=[output],
        )
        ref = await ArchiveService(self.sessions, self.archive).record(manifest)
        async with self.sessions.begin() as session:
            result = await session.get(DailyExport, day)
            if result is None:
                result = DailyExport(day=day)
                session.add(result)
            result.reference = output.model_dump(mode="json")
            result.manifest = ref.model_dump(mode="json")
            result.signature = signature
            result.snapshots = len(captures)
            result.published_at = datetime.now(UTC)
        return result
