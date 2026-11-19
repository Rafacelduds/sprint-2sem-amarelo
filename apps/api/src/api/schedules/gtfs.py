"""Leitura por tabela; não carrega shapes nem o histórico GPS."""

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile

from api.schedules.models import Departure, seconds

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def rows(archive: ZipFile, name: str, *, required: bool = True) -> Iterator[dict[str, str]]:
    matches = [item for item in archive.infolist() if item.filename == name]
    if not matches and not required:
        return
    if len(matches) != 1 or matches[0].file_size > 512 * 1024 * 1024:
        raise ValueError(f"tabela GTFS ausente, duplicada ou excessiva: {name}")
    with (
        archive.open(matches[0]) as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f,
    ):
        yield from csv.DictReader(f)


def gtfs_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def generate(path: Path, day: date, lines: set[str], sha256: str) -> list[Departure]:
    with ZipFile(path) as archive:
        active: set[str] = set()
        for row in rows(archive, "calendar.txt", required=False):
            if (
                gtfs_date(row["start_date"]) <= day <= gtfs_date(row["end_date"])
                and row[WEEKDAYS[day.weekday()]] == "1"
            ):
                active.add(row["service_id"])
        for row in rows(archive, "calendar_dates.txt", required=False):
            if gtfs_date(row["date"]) == day:
                if row["exception_type"] == "1":
                    active.add(row["service_id"])
                elif row["exception_type"] == "2":
                    active.discard(row["service_id"])
                else:
                    raise ValueError("exceção GTFS inválida")
        if not {"calendar.txt", "calendar_dates.txt"}.intersection(archive.namelist()):
            raise ValueError("GTFS sem calendário")
        route_names = {
            row["route_id"]: row["route_short_name"].strip() for row in rows(archive, "routes.txt")
        }
        if lines - set(route_names.values()):
            raise ValueError("GTFS sem referência para uma das linhas solicitadas")
        trips: dict[str, dict[str, str]] = {}
        for row in rows(archive, "trips.txt"):
            if row["route_id"] not in route_names:
                raise ValueError("trip sem route_id válido")
            if row["service_id"] in active and route_names[row["route_id"]] in lines:
                if row["trip_id"] in trips:
                    raise ValueError("trip_id duplicado")
                trips[row["trip_id"]] = row
        # Primeiro stop_sequence, independentemente da ordem física das linhas.
        first: dict[str, tuple[int, str]] = {}
        for row in rows(archive, "stop_times.txt"):
            trip = row["trip_id"]
            if trip in trips:
                sequence = int(row["stop_sequence"])
                if trip not in first or sequence < first[trip][0]:
                    first[trip] = (sequence, row["departure_time"])
                elif sequence == first[trip][0]:
                    raise ValueError("stop_sequence inicial duplicado")
        frequencies: dict[str, list[tuple[int, int, int, bool]]] = {}
        for row in rows(archive, "frequencies.txt", required=False):
            trip = row["trip_id"]
            if trip not in trips:
                continue
            start, end = seconds(row["start_time"]), seconds(row["end_time"])
            headway = int(row["headway_secs"])
            exact = row.get("exact_times", "") or "0"
            if start >= end or headway <= 0 or exact not in {"0", "1"}:
                raise ValueError("faixa de frequência inválida")
            frequencies.setdefault(trip, []).append((start, end, headway, exact == "1"))
        result: list[Departure] = []
        for trip, row in trips.items():
            if trip not in first or not first[trip][1]:
                raise ValueError("trip sem horário inicial")
            intervals = sorted(frequencies.get(trip, []))
            if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:], strict=False)):
                raise ValueError("faixas de frequência sobrepostas")
            times: list[tuple[int, str]] = []
            if intervals:
                for start, end, headway, exact in intervals:
                    grid = range(start, end, headway)
                    if len(result) + len(times) + len(grid) > 1_000_000:
                        raise ValueError("limite de partidas excedido")
                    times.extend(
                        (value, "gtfs_exact" if exact else "gtfs_frequency_estimate")
                        for value in grid
                    )
            else:
                times.append((seconds(first[trip][1]), "gtfs_fixed"))
            if len(result) + len(times) > 1_000_000:
                raise ValueError("limite de partidas excedido")
            for departure, kind in times:
                result.append(
                    Departure(
                        route_names[row["route_id"]],
                        row.get("direction_id", ""),
                        "gtfs",
                        day,
                        departure,
                        kind,
                        sha256,
                        trip,
                        len(result),
                    )
                )
        return result
