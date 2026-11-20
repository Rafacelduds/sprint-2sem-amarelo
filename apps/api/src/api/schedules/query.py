"""Consulta limitada e verificada dos derivados US04; não executa coleta."""

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from uuid import UUID

import duckdb
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, model_validator

from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive

Checksum = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0)]
Status = Literal["official", "gtfs", "gtfs_no_departures", "unavailable"]
Kind = Literal["official", "gtfs_fixed", "gtfs_exact", "gtfs_frequency_estimate"]
MAX_MANIFESTS = 1000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PARQUET_BYTES = 128 * 1024 * 1024


class RunNotFound(LookupError):
    pass


class PublishedLine(BaseModel):
    line: str
    status: Status
    source_sha256: Checksum | None = None
    expected: dict[str, Count] | None = None
    written: dict[str, Count] | Count | None = None
    declared_counts_match: bool | None = None


class Capture(BaseModel):
    captured_at: datetime
    reference: ObjectRef

    @model_validator(mode="after")
    def timezone_required(self) -> "Capture":
        if self.captured_at.tzinfo is None:
            raise ValueError("captura sem fuso")
        return self


class ScheduleManifest(BaseModel):
    run_id: UUID
    rule_version: Literal["us04-v1"]
    code_version: str = Field(pattern=r"^(working-tree|[0-9a-f]{40})$")
    started_at: datetime
    finished_at: datetime
    service_date: date
    day_type: Literal["U", "S", "D"]
    timezone: Literal["America/Sao_Paulo"]
    source_url: str | None = None
    validity: Literal["capture_reference_only_not_official_historical_validity"]
    operational_day_cutoff: None = None
    captures: list[Capture] = Field(default_factory=lambda: list[Capture]())
    inputs: list[ObjectRef]
    output: ObjectRef
    lines: list[PublishedLine] = Field(max_length=10000)
    official_lines_checked: Count
    official_lines_concordant: Count
    has_discrepancies: bool
    acceptance_30_lines: bool
    complete: bool

    @model_validator(mode="after")
    def consistent(self) -> "ScheduleManifest":
        if (
            self.started_at.tzinfo is None
            or self.finished_at.tzinfo is None
            or self.finished_at < self.started_at
            or len({line.line for line in self.lines}) != len(self.lines)
            or self.output.encoding != "identity"
            or self.output.key != f"derived/schedules/us04-v1/{self.output.sha256}.parquet"
        ):
            raise ValueError("manifesto de programação inconsistente")
        hashes = {ref.sha256 for ref in self.inputs}
        for line in self.lines:
            if line.status != "unavailable" and line.source_sha256 not in hashes:
                raise ValueError("fonte da linha não pertence ao manifesto")
            if line.status == "official" and (
                not isinstance(line.written, dict)
                or line.expected is None
                or line.declared_counts_match
                != (line.expected == {key: line.written.get(key, 0) for key in line.expected})
            ):
                raise ValueError("totais oficiais inconsistentes")
            if line.status in {"gtfs", "gtfs_no_departures"} and not isinstance(line.written, int):
                raise ValueError("total GTFS ausente")
        official = [line for line in self.lines if line.status == "official"]
        concordant = sum(line.declared_counts_match is True for line in official)
        if (
            self.official_lines_checked != len(official)
            or self.official_lines_concordant != concordant
            or self.has_discrepancies
            != any(line.declared_counts_match is False for line in official)
            or self.complete != all(line.status != "unavailable" for line in self.lines)
            or self.acceptance_30_lines
            != (
                len(self.lines) >= 30
                and all(line.declared_counts_match is True for line in self.lines)
            )
        ):
            raise ValueError("resumo do manifesto inconsistente")
        return self


class ScheduleRun(BaseModel):
    run_id: UUID
    service_date: date
    day_type: Literal["U", "S", "D"]
    timezone: str
    started_at: datetime
    finished_at: datetime
    rule_version: str
    code_version: str
    source_url: str | None
    validity: str
    operational_day_cutoff: None = None
    manifest_sha256: str
    parquet_sha256: str
    lines: list[PublishedLine]
    official_lines_checked: int
    official_lines_concordant: int
    has_discrepancies: bool
    acceptance_30_lines: bool
    complete: bool


class ScheduleCatalog(BaseModel):
    day: date
    runs: list[ScheduleRun]


class DepartureItem(BaseModel):
    direction: str
    direction_system: Literal["sptrans_itinerarios", "gtfs"]
    departure_seconds: int = Field(ge=0)
    time: str
    kind: Kind
    source_order: int = Field(ge=0)
    trip_id: str | None


class DirectionTotal(BaseModel):
    direction: str
    written: int
    declared: int | None


class ScheduleDepartures(BaseModel):
    run: ScheduleRun
    line: PublishedLine
    source_captured_at: datetime | None
    direction: str | None
    direction_totals: list[DirectionTotal]
    total: int
    offset: int
    limit: int
    items: list[DepartureItem]


def read_manifest(archive: S3Archive, ref: ObjectRef, directory: Path) -> ScheduleManifest:
    if ref.size > MAX_MANIFEST_BYTES or ref.encoding != "identity":
        raise ValueError("manifesto excessivo ou comprimido")
    path = directory / f"{ref.sha256}.json"
    archive.download(ref, path, max_bytes=MAX_MANIFEST_BYTES)
    manifest = ScheduleManifest.model_validate_json(path.read_bytes())
    if ref.key != f"manifests/schedules/{manifest.run_id}.json":
        raise ValueError("identidade divergente")
    return manifest


def public_run(manifest: ScheduleManifest, sha: str) -> ScheduleRun:
    # Nunca publicar endpoints de teste/privados ou campos livres de exceções da origem.
    official_url = "https://itinerariosapi.sptrans.com.br"
    source = official_url if (manifest.source_url or "").rstrip("/") == official_url else None
    return ScheduleRun(
        **manifest.model_dump(exclude={"captures", "inputs", "output", "source_url"}),
        source_url=source,
        manifest_sha256=sha,
        parquet_sha256=manifest.output.sha256,
    )


def catalog(archive: S3Archive, day: date) -> ScheduleCatalog:
    runs: list[ScheduleRun] = []
    with TemporaryDirectory(prefix="schedule-catalog-") as temporary:
        for index, ref in enumerate(archive.objects("manifests/schedules/")):
            if index >= MAX_MANIFESTS:
                raise ValueError("catálogo requer indexação")
            manifest = read_manifest(archive, ref, Path(temporary))
            if manifest.service_date == day:
                runs.append(public_run(manifest, ref.sha256))
    return ScheduleCatalog(
        day=day, runs=sorted(runs, key=lambda run: (run.finished_at, str(run.run_id)), reverse=True)
    )


def departures(
    archive: S3Archive,
    run_id: UUID,
    line: str,
    direction: str | None,
    offset: int,
    limit: int,
) -> ScheduleDepartures:
    try:
        ref = archive.reference(f"manifests/schedules/{run_id}.json")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            raise RunNotFound("execução não publicada") from None
        raise
    with TemporaryDirectory(prefix="schedule-query-") as temporary:
        root = Path(temporary)
        manifest = read_manifest(archive, ref, root)
        selected = next((row for row in manifest.lines if row.line == line), None)
        if selected is None:
            raise LookupError("linha não incluída nesta publicação")
        if manifest.output.size > MAX_PARQUET_BYTES:
            raise ValueError("derivado excessivo")
        parquet = root / "departures.parquet"
        archive.download(manifest.output, parquet, max_bytes=MAX_PARQUET_BYTES)
        with duckdb.connect(
            str(root / "query.duckdb"),
            config={
                "memory_limit": "64MB",
                "threads": 1,
            },
        ) as connection:
            connection.execute(
                "CREATE TABLE departures AS SELECT * FROM read_parquet(?)", [str(parquet)]
            )
            # Consultar apenas a tabela local, sem extensões, rede ou SQL do usuário.
            connection.execute("SET enable_external_access=false")
            groups = connection.execute("""
                SELECT line, direction, direction_system, kind, source_sha256,
                       service_date, count(*) FROM departures GROUP BY ALL
            """).fetchall()
            totals: dict[str, dict[str, int]] = {row.line: {} for row in manifest.lines}
            published = {row.line: row for row in manifest.lines}
            for code, sense, system, kind, sha, day, count in groups:
                row = published.get(str(code))
                if (
                    row is None
                    or row.status in {"unavailable", "gtfs_no_departures"}
                    or sha != row.source_sha256
                    or day != manifest.service_date
                    or (
                        row.status == "official"
                        and (system != "sptrans_itinerarios" or kind != "official")
                    )
                    or (
                        row.status == "gtfs"
                        and (
                            system != "gtfs"
                            or kind not in {"gtfs_fixed", "gtfs_exact", "gtfs_frequency_estimate"}
                        )
                    )
                    or sense not in {"0", "1", ""}
                ):
                    raise ValueError("derivado diverge da procedência")
                total = totals[str(code)]
                total[str(sense)] = total.get(str(sense), 0) + int(count)
            for row in manifest.lines:
                counts = totals[row.line]
                if isinstance(row.written, dict):
                    if any(
                        counts.get(key, 0) != value for key, value in row.written.items()
                    ) or any(count != row.written.get(key, 0) for key, count in counts.items()):
                        raise ValueError("totais do derivado divergentes")
                elif isinstance(row.written, int) and sum(counts.values()) != row.written:
                    raise ValueError("total do derivado divergente")
            where = "line = ?"
            params: list[object] = [line]
            if direction is not None:
                where += " AND direction = ?"
                params.append("" if direction == "unknown" else direction)
            count_row = connection.execute(
                f"SELECT count(*) FROM departures WHERE {where}", params
            ).fetchone()
            if count_row is None:
                raise ValueError("contagem ausente")
            total = int(count_row[0])
            rows = connection.execute(
                f"""SELECT direction, direction_system, departure_seconds, kind,
                           source_order, trip_id FROM departures WHERE {where}
                    ORDER BY source_order, direction, departure_seconds, trip_id
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
        expected = selected.expected or {}
        directions = totals[line]
        source_time = next(
            (
                capture.captured_at
                for capture in reversed(manifest.captures)
                if capture.reference.sha256 == selected.source_sha256
            ),
            None,
        )
        return ScheduleDepartures(
            run=public_run(manifest, ref.sha256),
            line=selected,
            source_captured_at=source_time,
            direction=direction,
            direction_totals=[
                DirectionTotal(
                    direction=key, written=directions.get(key, 0), declared=expected.get(key)
                )
                for key in sorted(set(directions) | set(expected))
            ],
            total=total,
            offset=offset,
            limit=limit,
            items=[
                DepartureItem(
                    direction=str(sense),
                    direction_system=system,
                    departure_seconds=seconds,
                    time=f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}",
                    kind=kind,
                    source_order=order,
                    trip_id=trip,
                )
                for sense, system, seconds, kind, order, trip in rows
            ],
        )
