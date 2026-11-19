import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import duckdb
import httpx
from pydantic import TypeAdapter

from api.gtfs.catalog import public_source_url
from api.gtfs.source import copy_local, inspect_feed
from api.schedules.gtfs import generate
from api.schedules.models import CatalogLine, Departure, OfficialLine, official_departures
from api.storage.contracts import ObjectRef
from api.storage.s3 import S3Archive, digest

RULE_VERSION = "us04-v1"


class SourceUnavailable(RuntimeError):
    pass


class ArchiveFailure(RuntimeError):
    pass


class OfficialSource:
    def __init__(self, client: httpx.Client, *, retries: int = 3, backoff: float = 1):
        self.client, self.retries, self.backoff = client, retries, backoff

    def fetch(self, endpoint: str, body: dict[str, int] | None = None) -> bytes:
        for attempt in range(self.retries):
            try:
                with self.client.stream("POST", endpoint, json=body) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise SourceUnavailable(f"http_{response.status_code}")
                    if not response.is_success:
                        raise ValueError(f"http_{response.status_code}")
                    chunks = bytearray()
                    for block in response.iter_bytes():
                        chunks.extend(block)
                        if len(chunks) > 8 * 1024 * 1024:
                            raise ValueError("resposta excessiva")
                    return bytes(chunks)
            except (httpx.TransportError, SourceUnavailable):
                if attempt + 1 == self.retries:
                    raise SourceUnavailable("tentativas esgotadas") from None
                time.sleep(self.backoff * 2**attempt)
        raise SourceUnavailable("sem tentativas")


def write_parquet(path: Path, departures: list[Departure]) -> None:
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE departures (
                line VARCHAR, direction VARCHAR, direction_system VARCHAR,
                service_date DATE, departure_seconds INTEGER, kind VARCHAR,
                source_sha256 VARCHAR, trip_id VARCHAR, source_order INTEGER
            )
        """)
        if departures:
            connection.begin()
            connection.executemany(
                "INSERT INTO departures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [list(asdict(item).values()) for item in departures],
            )
            connection.commit()
        connection.execute("COPY departures TO ? (FORMAT PARQUET)", [str(path)])


def run(
    source: OfficialSource,
    archive: S3Archive,
    output: Path,
    *,
    day: date,
    day_type: str,
    lines: list[str] | None = None,
    sample: int = 30,
    gtfs_file: Path | None = None,
    gtfs_loader: Callable[[Path], Path | None] | None = None,
    code_version: str = "working-tree",
    interval: float = 0.5,
) -> dict[str, Any]:
    started = datetime.now(UTC)
    if day != started.astimezone(ZoneInfo("America/Sao_Paulo")).date():
        raise ValueError(
            "captura oficial só pode representar o dia atual; não inferir vigência passada"
        )
    run_id = str(uuid4())
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    inputs: list[ObjectRef] = []
    captures: list[dict[str, object]] = []

    def preserve(payload: bytes, name: str) -> str:
        captured_at = datetime.now(UTC).isoformat()
        sha = hashlib.sha256(payload).hexdigest()
        local = directory / name
        local.write_bytes(payload)
        try:
            ref = archive.put(
                local,
                f"raw/schedules/sptrans/{sha}.json",
                content_type="application/json",
                resume=True,
            )
        except Exception as exc:
            raise ArchiveFailure(type(exc).__name__) from exc
        inputs.append(ref)
        captures.append(
            {
                "name": name,
                "captured_at": captured_at,
                "reference": ref.model_dump(mode="json"),
            }
        )
        return sha

    catalog_error: str | None = None
    catalog: dict[str, int] = {}
    try:
        payload = source.fetch("RetornarLinhasTeste")
        preserve(payload, "catalog.json")
        for item in TypeAdapter(list[CatalogLine]).validate_json(payload):
            code = item.codigo.strip()
            if code in catalog:
                raise ValueError("código duplicado no catálogo")
            catalog[code] = item.CdPjOID
    except (SourceUnavailable, ValueError) as exc:
        catalog_error = type(exc).__name__
        catalog = {}
        if not lines:
            raise SourceUnavailable("catálogo indisponível; informe linhas explícitas") from None
    selected = sorted(set(lines)) if lines else sorted(catalog)[:sample]
    if not selected or sample < 1:
        raise ValueError("nenhuma linha selecionada")
    all_departures: list[Departure] = []
    report_lines: list[dict[str, object]] = []
    missing: list[tuple[str, str]] = []
    for line in selected:
        time.sleep(interval)
        try:
            if line not in catalog:
                raise SourceUnavailable(catalog_error or "linha ausente do catálogo")
            payload = source.fetch("BuscarDetalheLinhaTeste", {"codPlanejamento": catalog[line]})
            sha = preserve(payload, f"line-{len(report_lines)}.json")
            detail = OfficialLine.model_validate_json(payload)
            departures, expected = official_departures(detail, line, day, day_type, sha)
            actual = Counter(item.direction for item in departures)
            counts_match = all(actual[direction] == count for direction, count in expected.items())
            all_departures.extend(departures)
            report_lines.append(
                {
                    "line": line,
                    "status": "official",
                    "source_sha256": sha,
                    "expected": expected,
                    "written": dict(actual),
                    "declared_counts_match": counts_match,
                    "warning": None if counts_match else "published_total_differs_from_times",
                }
            )
        except (SourceUnavailable, ValueError) as exc:
            # Falha da origem pode usar a alternativa; erro de armazenamento propaga.
            # Nenhuma combinação automática de sentidos entre fontes diferentes.
            missing.append((line, type(exc).__name__))
            report_lines.append(
                {
                    "line": line,
                    "status": "unavailable",
                    "reason": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
    if missing and gtfs_file is None and gtfs_loader is not None:
        gtfs_file = gtfs_loader(directory)
    if missing and gtfs_file:
        snapshot = directory / "gtfs-input.zip"
        copy_local(gtfs_file, snapshot, max_bytes=512 * 1024 * 1024)
        metadata = inspect_feed(snapshot)
        if not metadata.starts_on <= day <= metadata.ends_on:
            raise ValueError("GTFS fora da cobertura declarada; alternativa recusada")
        ref = archive.put(
            snapshot,
            f"raw/schedules/gtfs/{metadata.sha256}.zip",
            content_type="application/zip",
            resume=True,
        )
        inputs.append(ref)
        candidates = generate(snapshot, day, {line for line, _ in missing}, metadata.sha256)
        all_departures.extend(candidates)
        for line_report in report_lines:
            if line_report["status"] == "unavailable":
                subset = [item for item in candidates if item.line == line_report["line"]]
                line_report.update(
                    {
                        "status": "gtfs" if subset else "gtfs_no_departures",
                        "source_sha256": metadata.sha256,
                        "written": len(subset),
                    }
                )
    parquet = directory / "departures.parquet"
    write_parquet(parquet, all_departures)
    # Ler o artefato efetivamente escrito, além de conferir os totais em memória.
    with duckdb.connect() as connection:
        counts = connection.execute(
            "SELECT line, count(*) FROM read_parquet(?) GROUP BY line", [str(parquet)]
        ).fetchall()
    persisted = {str(line): int(count) for line, count in counts}
    if persisted != dict(Counter(item.line for item in all_departures)):
        raise ValueError("contagem Parquet divergente")
    sha, _ = digest(parquet)
    derivative = archive.put(
        parquet,
        f"derived/schedules/{RULE_VERSION}/{sha}.parquet",
        content_type="application/vnd.apache.parquet",
        resume=True,
    )
    report: dict[str, Any] = {
        "run_id": run_id,
        "rule_version": RULE_VERSION,
        "code_version": code_version,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "service_date": day.isoformat(),
        "day_type": day_type,
        "day_type_basis": "explicit_operator_selection",
        "timezone": "America/Sao_Paulo",
        "source_url": public_source_url(str(source.client.base_url)),
        "validity": "capture_reference_only_not_official_historical_validity",
        "operational_day_cutoff": None,
        "captures": captures,
        "inputs": [ref.model_dump(mode="json") for ref in inputs],
        "output": derivative.model_dump(mode="json"),
        "lines": report_lines,
        "official_lines_checked": sum(row["status"] == "official" for row in report_lines),
        "official_lines_concordant": sum(
            row.get("declared_counts_match") is True for row in report_lines
        ),
        "has_discrepancies": any(row.get("declared_counts_match") is False for row in report_lines),
        "acceptance_30_lines": len(report_lines) >= 30
        and all(row.get("declared_counts_match") is True for row in report_lines),
        "complete": all(
            row["status"] in {"official", "gtfs", "gtfs_no_departures"} for row in report_lines
        ),
    }
    path = directory / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    archive.put(path, f"manifests/schedules/{run_id}.json", content_type="application/json")
    return report
