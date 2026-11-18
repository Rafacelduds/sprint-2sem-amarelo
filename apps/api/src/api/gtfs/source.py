"""Download limitado e inspeção de ZIP sem extrair nem modificar os brutos."""

import asyncio
import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx


class GtfsError(Exception):
    """Código estável, sem URL, credencial ou conteúdo recebido."""


@dataclass(frozen=True)
class FeedMetadata:
    sha256: str
    size: int
    starts_on: date
    ends_on: date
    coverage_basis: str
    publisher_version: str | None


REQUIRED_COLUMNS = {
    "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
    "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
    "routes.txt": {"route_id", "route_type"},
    "trips.txt": {"route_id", "service_id", "trip_id"},
    "stop_times.txt": {"trip_id", "stop_id", "stop_sequence"},
}


def _date(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        raise ValueError("invalid_date")
    return datetime.strptime(value, "%Y%m%d").date()


def inspect_feed(path: Path, *, max_expanded_bytes: int = 4_294_967_296) -> FeedMetadata:
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        while chunk := raw.read(1024 * 1024):
            digest.update(chunk)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(set(names)) != len(names) or any(
                "/" in name or "\\" in name or name in {".", ".."} for name in names
            ):
                raise GtfsError("invalid_zip_layout")
            if sum(item.file_size for item in archive.infolist()) > max_expanded_bytes:
                raise GtfsError("expanded_feed_too_large")
            if any(item.flag_bits & 1 for item in archive.infolist()):
                raise GtfsError("encrypted_zip")
            for name, columns in REQUIRED_COLUMNS.items():
                if name not in names:
                    raise GtfsError("missing_gtfs_table")
                with (
                    archive.open(name) as member,
                    io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream,
                ):
                    reader = csv.DictReader(stream)
                    if not columns.issubset(reader.fieldnames or []) or next(reader, None) is None:
                        raise GtfsError("invalid_gtfs_columns")
            if not {"calendar.txt", "calendar_dates.txt"}.intersection(names):
                raise GtfsError("missing_gtfs_calendar")
            # Verifica CRC de todos os membros em blocos; nunca descompacta no filesystem.
            if archive.testzip() is not None:
                raise GtfsError("invalid_zip_crc")
            starts: list[date] = []
            ends: list[date] = []
            publisher_version: str | None = None
            basis = "calendar_extent"
            if "feed_info.txt" in names:
                with (
                    archive.open("feed_info.txt") as member,
                    io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream,
                ):
                    info = next(csv.DictReader(stream), {})
                    publisher_version = info.get("feed_version") or None
                    if info.get("feed_start_date") and info.get("feed_end_date"):
                        starts.append(_date(info["feed_start_date"]))
                        ends.append(_date(info["feed_end_date"]))
                        basis = "feed_info"
            if not starts:
                for name in ("calendar.txt", "calendar_dates.txt"):
                    if name not in names:
                        continue
                    with (
                        archive.open(name) as member,
                        io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream,
                    ):
                        for row in csv.DictReader(stream):
                            if name == "calendar.txt":
                                start, end = _date(row["start_date"]), _date(row["end_date"])
                                if end < start:
                                    raise GtfsError("invalid_gtfs_dates")
                                starts.append(start)
                                ends.append(end)
                            elif row["exception_type"] == "1":
                                added = _date(row["date"])
                                starts.append(added)
                                ends.append(added)
            if not starts or min(starts) > max(ends):
                raise GtfsError("invalid_gtfs_dates")
            return FeedMetadata(
                digest.hexdigest(),
                path.stat().st_size,
                min(starts),
                max(ends),
                basis,
                publisher_version,
            )
    except (zipfile.BadZipFile, UnicodeError, ValueError, KeyError, csv.Error, RuntimeError):
        raise GtfsError("invalid_gtfs") from None


async def download(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    *,
    max_bytes: int = 268_435_456,
    attempts: int = 3,
) -> None:
    for attempt in range(attempts):
        try:
            async with client.stream(
                "GET", url, headers={"Accept-Encoding": "identity"}
            ) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    raise GtfsError("source_temporarily_unavailable")
                if response.status_code != 200:
                    raise GtfsError("source_rejected")
                size = 0
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise GtfsError("download_too_large")
                        output.write(chunk)
                return
        except httpx.TransportError:
            error = "source_transport_error"
        except GtfsError as exc:
            if str(exc) != "source_temporarily_unavailable":
                raise
            error = str(exc)
        if attempt + 1 < attempts:
            await asyncio.sleep(2**attempt)
    raise GtfsError(error)
