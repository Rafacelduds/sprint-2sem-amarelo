import asyncio
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.collection.models import CollectionCycle, VehiclePosition
from api.gtfs.catalog import resolve_version
from api.gtfs.models import GtfsCapture
from api.reliability.models import (
    DailyReport,
    Gap,
    GtfsPeriod,
    ReliabilityReport,
    ScheduleReference,
    UsedVersion,
)
from api.storage.s3 import S3Archive

LOCAL = ZoneInfo("America/Sao_Paulo")


class ScheduleLine(BaseModel):
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ScheduleManifest(BaseModel):
    run_id: str
    service_date: date
    started_at: datetime
    finished_at: datetime
    lines: list[ScheduleLine]
    complete: bool
    has_discrepancies: bool


def schedule_references(
    archive: S3Archive,
    day: date,
    known_at: datetime | None = None,
) -> list[ScheduleReference]:
    """Lê apenas manifestos pequenos, verificando bytes; nunca lê os GPS."""
    result: dict[str, ScheduleReference] = {}
    with TemporaryDirectory(prefix="us13-schedules-") as directory:
        for index, ref in enumerate(archive.objects("manifests/schedules/")):
            if ref.size > 8 * 1024 * 1024 or ref.encoding != "identity":
                raise ValueError("manifesto US04 excessivo ou codificação inesperada")
            path = Path(directory) / str(index)
            archive.download(ref, path)
            manifest = ScheduleManifest.model_validate_json(path.read_bytes())
            if (
                manifest.started_at.tzinfo is None
                or manifest.finished_at.tzinfo is None
                or manifest.finished_at < manifest.started_at
            ):
                raise ValueError("período inválido no manifesto US04")
            if manifest.service_date != day:
                continue
            if known_at is not None and manifest.finished_at > known_at:
                continue
            item = ScheduleReference(
                run_id=manifest.run_id,
                started_at=manifest.started_at,
                finished_at=manifest.finished_at,
                manifest_sha256=ref.sha256,
                source_hashes=sorted(
                    {line.source_sha256 for line in manifest.lines if line.source_sha256}
                ),
                complete=manifest.complete,
                has_discrepancies=manifest.has_discrepancies,
            )
            if item.run_id in result and result[item.run_id] != item:
                raise ValueError("manifestos US04 conflitantes para a mesma execução")
            result[item.run_id] = item
    return sorted(result.values(), key=lambda item: (item.started_at, item.run_id))


def build_gaps(
    cycles: list[CollectionCycle],
    start: datetime,
    end: datetime,
    interval: int,
) -> list[Gap]:
    gaps: list[Gap] = []

    def append(left: datetime, right: datetime, cause: str) -> None:
        left, right = max(start, left), min(end, right)
        if left >= right:
            return
        gap = Gap.model_validate(
            dict(
                start=left,
                end=right,
                cause=cause,
                evidence="inferred_absence" if cause == "no_cycle_record" else "recorded_cycle",
                possible_maintenance=cause == "origin_failure",
            )
        )
        if gaps and gaps[-1].end == left and gaps[-1].cause == gap.cause:
            gaps[-1].end = right
        else:
            gaps.append(gap)

    cursor = start
    # Recuperações podem registrar mais de um ciclo com o mesmo agendamento.
    grouped: dict[datetime, list[CollectionCycle]] = {}
    for cycle in cycles:
        grouped.setdefault(cycle.scheduled_at, []).append(cycle)
    ordered = sorted(grouped.items())
    priority = {
        "success": 0,
        "running": 2,
        "interrupted": 3,
        "origin_failure": 4,
        "storage_failure": 5,
    }
    for index, (at, coincident) in enumerate(ordered):
        cycle = max(coincident, key=lambda item: (priority.get(item.status, 1), item.status))
        width = max(item.interval_seconds or interval for item in coincident)
        next_at = ordered[index + 1][0] if index + 1 < len(ordered) else end
        until = min(at + timedelta(seconds=width), next_at, end)
        # Até 5 s de atraso do agendador não comprovam um ciclo perdido.
        if next_at <= at + timedelta(seconds=width + 5):
            until = min(next_at, end)
        append(cursor, at, "no_cycle_record")
        if cycle.status != "success":
            cause = (
                cycle.status
                if cycle.status
                in {
                    "origin_failure",
                    "storage_failure",
                    "interrupted",
                }
                else "unfinished_cycle"
                if cycle.status == "running"
                else "unknown_cycle_status"
            )
            append(at, until, cause)
        cursor = max(cursor, until)
    append(cursor, end, "no_cycle_record")
    return gaps


async def build_report(
    session: AsyncSession,
    day: date,
    *,
    now: datetime,
    interval: int,
    source_id: str,
    schedules: list[ScheduleReference],
) -> ReliabilityReport:
    if now.tzinfo is None or not 15 <= interval <= 60:
        raise ValueError("instante com fuso e intervalo entre 15 e 60 s são obrigatórios")
    start = datetime.combine(day, time.min, LOCAL).astimezone(UTC)
    day_end = datetime.combine(day + timedelta(days=1), time.min, LOCAL).astimezone(UTC)
    end = min(day_end, now)
    if end <= start:
        raise ValueError("dia futuro ou ainda sem período observável")
    cycles = list(
        (
            await session.scalars(
                select(CollectionCycle)
                .where(
                    CollectionCycle.scheduled_at >= start - timedelta(seconds=65),
                    CollectionCycle.scheduled_at < end,
                )
                .order_by(CollectionCycle.scheduled_at, CollectionCycle.id)
            )
        ).all()
    )
    relevant = [
        cycle
        for cycle in cycles
        if cycle.scheduled_at + timedelta(seconds=(cycle.interval_seconds or interval) + 5) > start
    ]
    gaps = build_gaps(relevant, start, end, interval)
    captures = (
        await session.scalars(
            select(GtfsCapture.captured_at)
            .where(
                GtfsCapture.source_id == source_id,
                GtfsCapture.captured_at > start,
                GtfsCapture.captured_at < end,
            )
            .distinct()
            .order_by(GtfsCapture.captured_at)
        )
    ).all()
    bounds = [start, *captures, end]
    periods: list[GtfsPeriod] = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        sha = await resolve_version(session, day, left, source_id=source_id)
        if periods and periods[-1].sha256 == sha:
            periods[-1].end = right
        else:
            periods.append(GtfsPeriod(start=left, end=right, sha256=sha))
    # Agregação no banco, sem materializar posições nem corpos brutos.
    used = (
        await session.execute(
            select(
                VehiclePosition.gtfs_version_sha256,
                VehiclePosition.gtfs_link_status,
                func.count(),
            )
            .where(VehiclePosition.collected_at >= start, VehiclePosition.collected_at < end)
            .group_by(VehiclePosition.gtfs_version_sha256, VehiclePosition.gtfs_link_status)
            .order_by(VehiclePosition.gtfs_version_sha256, VehiclePosition.gtfs_link_status)
        )
    ).all()
    return ReliabilityReport(
        day=day,
        generated_at=now,
        period_start=start,
        period_end=end,
        provisional=end < day_end,
        fallback_interval_seconds=interval,
        cycles=sum(cycle.scheduled_at >= start for cycle in cycles),
        legacy_interval_cycles=sum(c.interval_seconds is None for c in relevant),
        gaps=gaps,
        gap_seconds=sum((gap.end - gap.start).total_seconds() for gap in gaps),
        gtfs_source_id=source_id,
        gtfs_reference_periods=periods,
        gtfs_used=[
            UsedVersion(sha256=sha, link_status=status, observations=count)
            for sha, status, count in used
        ],
        schedule_references=schedules,
        schedules_status="references_found" if schedules else "no_manifest_for_day",
        limitations=[
            "Ausência de ciclo não comprova ausência de ônibus nem indisponibilidade da origem.",
            "Falhas podem ser parciais, inclusive restritas a garagens; não medir perda de GPS.",
            "Manutenção da origem é apenas possível, nunca confirmada por este relatório.",
            "GTFS de referência segue a política US02; cobertura não comprova vigência histórica.",
            "Versões usadas são agregadas pela data de coleta; o vínculo usa o dia local do GPS.",
            "Manifestos US04 são referências de captura, sem inferir vigência entre execuções.",
            "Ciclos históricos sem intervalo usam o valor informado nesta geração.",
        ],
    )


async def publish(
    sessions: async_sessionmaker[AsyncSession],
    archive: S3Archive,
    day: date,
    *,
    now: datetime,
    interval: int,
    source_id: str,
    code_version: str = "working-tree",
) -> ReliabilityReport:
    schedules = await asyncio.to_thread(schedule_references, archive, day, now)
    async with sessions.begin() as session:
        # Evita misturar versões de tabelas durante a geração.
        from sqlalchemy import text

        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        report = await build_report(
            session, day, now=now, interval=interval, source_id=source_id, schedules=schedules
        )
        report = ReliabilityReport.model_validate(
            {**report.model_dump(), "code_version": code_version}
        )
        values = dict(day=day, generated_at=now, document=report.model_dump(mode="json"))
        statement = insert(DailyReport).values(**values)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[DailyReport.day],
                set_=values,
                where=DailyReport.generated_at <= now,
            )
        )
    return report
