import asyncio
import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import UUID, uuid4

import pyarrow  # pyright: ignore[reportMissingTypeStubs]
import pyarrow.parquet  # pyright: ignore[reportMissingTypeStubs]
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
    # PyArrow não fornece tipos completos. Restringir Any à fronteira do escritor.
    arrow = cast(Any, pyarrow)
    parquet = cast(Any, pyarrow.parquet)
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
    schema = arrow.schema(
        [
            ("captura_id", arrow.string()),
            ("ciclo_id", arrow.string()),
            ("coletado_em", arrow.timestamp("us", tz="UTC")),
            ("endpoint", arrow.string()),
            ("empresa", arrow.int32()),
            ("fonte", arrow.string()),
            ("sha256_original", arrow.string()),
            ("corpo_original", arrow.binary()),
        ],
        metadata={k.encode(): v.encode() for k, v in metadata.items()},
    )
    # Cada chamada descarrega um row group. Corpos não ficam retidos até o fim do dia.
    rows: list[dict[str, object]] = []
    buffered_bytes = 0
    with parquet.ParquetWriter(
        path, schema, compression="zstd", use_dictionary=False, write_statistics=False
    ) as writer:

        def flush() -> None:
            if rows:
                writer.write_table(arrow.Table.from_pylist(rows, schema=schema))
                rows.clear()

        for capture in captures:
            downloaded = path.with_suffix(".payload")
            try:
                archive.download(capture.ref, downloaded)
                body = downloaded.read_bytes()
                if capture.ref.encoding == "gzip":
                    body = gzip.decompress(body)
                if rows and (buffered_bytes + len(body) > 8 * 1024 * 1024 or len(rows) >= 256):
                    flush()
                    buffered_bytes = 0
                rows.append(
                    {
                        "captura_id": str(capture.id),
                        "ciclo_id": str(capture.cycle_id),
                        "coletado_em": capture.collected_at,
                        "endpoint": capture.endpoint,
                        "empresa": capture.company,
                        "fonte": SOURCE,
                        "sha256_original": capture.ref.sha256,
                        "corpo_original": body,
                    }
                )
                buffered_bytes += len(body)
            finally:
                downloaded.unlink(missing_ok=True)
        flush()


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
