"""Read the immutable US02 archive and build a disposable spatial cache for US22."""

import asyncio
import csv
import hashlib
import io
import math
import re
import sqlite3
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from typing import TYPE_CHECKING, Literal

import boto3
from botocore.config import Config
from sqlalchemy import select

from api.config import get_settings
from api.gtfs.models import GtfsCapture, GtfsVersion

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@dataclass(frozen=True)
class FeedReference:
    version: str
    captured_at: datetime
    source: str
    bucket: str
    key: str
    size: int


@dataclass(frozen=True)
class Route:
    id: str
    color: str | None
    # (headsign normalized, GTFS direction, shape_id)
    trips: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class Match:
    route: Route
    direction: str
    shapes: tuple[str, ...]
    status: Literal["matched", "unmatched", "ambiguous"]


def normalize_destination(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    words: list[str] = re.findall(r"[a-z0-9]+", value.lower())
    abbreviations: dict[str, str] = {
        "term": "terminal",
        "jd": "jardim",
        "vl": "vila",
        "pq": "parque",
        "prq": "parque",
        "pca": "praca",
    }
    return " ".join((abbreviations.get(word) or word) for word in words)


def read_table(archive: zipfile.ZipFile, table: str) -> Iterator[dict[str, str]]:
    with (
        archive.open(table) as member,
        io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream,
    ):
        for row in csv.DictReader(stream):
            yield {str(key): str(value or "") for key, value in row.items() if key is not None}


class Feed:
    def __init__(self, routes: dict[str, list[Route]], database: Path):
        self.routes = routes
        self.database = database

    def match(self, label: str, destination: str) -> Match | None:
        routes = self.routes.get(label.strip().upper(), [])
        if len(routes) != 1:
            return None
        route = routes[0]
        headsign = normalize_destination(destination)
        trips = [trip for trip in route.trips if headsign and trip[0] == headsign]
        directions = {trip[1] for trip in trips}
        if len(directions) != 1:
            return Match(route, "", (), "ambiguous" if directions else "unmatched")
        direction = next(iter(directions))
        return Match(route, direction, tuple(sorted({t[2] for t in trips if t[2]})), "matched")

    def geometry(self, shapes: tuple[str, ...]) -> list[list[tuple[float, float]]]:
        result: list[list[tuple[float, float]]] = []
        connection = sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        try:
            for shape in shapes:
                coordinates = [
                    (float(lon), float(lat))
                    for lon, lat in connection.execute(
                        "SELECT lon,lat FROM shape_points WHERE shape_id=? ORDER BY sequence",
                        (shape,),
                    )
                ]
                if len(coordinates) >= 2:
                    result.append(coordinates)
        finally:
            connection.close()
        return result


def prepare_feed(path: Path, database: Path) -> Feed:
    """CSV streams and SQLite keep the 60+ MB shapes table out of Python object memory."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(i.file_size for i in archive.infolist()) > 4_294_967_296
        ):
            raise ValueError("invalid_gtfs_archive")
        required = {"routes.txt", "trips.txt"}
        if not required.issubset(names):
            raise ValueError("missing_map_tables")
        trips: dict[str, set[tuple[str, str, str]]] = {}
        for row in read_table(archive, "trips.txt"):
            if row.get("direction_id") in {"0", "1"}:
                trips.setdefault(row["route_id"], set()).add(
                    (
                        normalize_destination(row.get("trip_headsign", "")),
                        row["direction_id"],
                        row.get("shape_id", ""),
                    )
                )
        routes: dict[str, list[Route]] = {}
        for row in read_table(archive, "routes.txt"):
            if row.get("route_type") != "3":
                continue
            color = row.get("route_color", "").strip().upper()
            route = Route(
                row["route_id"],
                f"#{color}" if re.fullmatch(r"[0-9A-F]{6}", color) else None,
                tuple(sorted(trips.get(row["route_id"], set()))),
            )
            label = (row.get("route_short_name") or row["route_id"]).strip().upper()
            routes.setdefault(label, []).append(route)
        if not database.exists():
            build_shapes(archive, database)
        return Feed(routes, database)


def build_shapes(archive: zipfile.ZipFile, database: Path) -> None:
    with NamedTemporaryFile(dir=database.parent, suffix=".sqlite", delete=False) as temp:
        temporary = Path(temp.name)
    connection = sqlite3.connect(temporary)
    invalid: set[str] = set()
    try:
        connection.execute(
            "CREATE TABLE shape_points (shape_id TEXT, sequence INTEGER, "
            "lon REAL, lat REAL, PRIMARY KEY(shape_id,sequence)) WITHOUT ROWID"
        )
        for row in read_table(archive, "shapes.txt") if "shapes.txt" in archive.namelist() else ():
            shape = row.get("shape_id", "")
            if not shape or shape in invalid:
                continue
            try:
                sequence = int(row["shape_pt_sequence"])
                lon, lat = float(row["shape_pt_lon"]), float(row["shape_pt_lat"])
                if not (
                    sequence >= 0
                    and math.isfinite(lon)
                    and math.isfinite(lat)
                    and -180 <= lon <= 180
                    and -90 <= lat <= 90
                ):
                    raise ValueError("invalid_coordinate")
                connection.execute(
                    "INSERT INTO shape_points VALUES(?,?,?,?)", (shape, sequence, lon, lat)
                )
            except (ValueError, KeyError, sqlite3.IntegrityError):
                invalid.add(shape)
        connection.executemany("DELETE FROM shape_points WHERE shape_id=?", [(s,) for s in invalid])
        connection.commit()
        connection.close()
        temporary.replace(database)
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def archive_client() -> "S3Client":
    s = get_settings()
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=s.s3_endpoint_url,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 1}),
    )


def load_feed(reference: FeedReference) -> Feed:
    directory = get_settings().network_cache_dir.resolve() / reference.version
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "feed.zip"
    if not path.exists() or path.stat().st_size != reference.size:
        with NamedTemporaryFile(dir=directory, suffix=".zip", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            body = archive_client().get_object(Bucket=reference.bucket, Key=reference.key)["Body"]
            digest = hashlib.sha256()
            size = 0
            try:
                with temporary.open("wb") as output:
                    for chunk in body.iter_chunks(1024 * 1024):
                        size += len(chunk)
                        if size > reference.size or size > 268_435_456:
                            raise ValueError("archive_too_large")
                        digest.update(chunk)
                        output.write(chunk)
            finally:
                body.close()
            if size != reference.size or digest.hexdigest() != reference.version:
                raise ValueError("archive_hash_mismatch")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        with path.open("rb") as stream:
            valid = hashlib.file_digest(stream, "sha256").hexdigest() == reference.version
        if not valid:
            # Windows requires the reader to be closed before removing the corrupt cache.
            path.unlink()
            raise ValueError("cache_hash_mismatch")
    return prepare_feed(path, directory / "shapes-v1.sqlite")


async def latest_reference() -> FeedReference | None:
    from api.db.session import SessionFactory

    now = datetime.now(UTC)
    # Same coverage policy as US02; live map uses today's São Paulo civil date.
    from zoneinfo import ZoneInfo

    today = now.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(GtfsCapture, GtfsVersion)
                .join(GtfsVersion, GtfsCapture.version_sha256 == GtfsVersion.sha256)
                .where(
                    GtfsCapture.source_id == get_settings().gtfs_source_id,
                    GtfsCapture.captured_at <= now,
                    GtfsVersion.starts_on <= today,
                    GtfsVersion.ends_on >= today,
                )
                .order_by(GtfsCapture.captured_at.desc(), GtfsCapture.id.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        capture, version = row
        return FeedReference(
            version.sha256,
            capture.captured_at,
            capture.source_url,
            version.bucket,
            version.object_key,
            version.size,
        )


class FeedProvider:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.next_check = 0.0
        self.current: tuple[FeedReference, Feed] | None = None

    async def get(self) -> tuple[FeedReference, Feed] | None:
        async with self.lock:
            if monotonic() < self.next_check:
                return self.current
            try:
                reference = await asyncio.wait_for(latest_reference(), timeout=8)
                if reference is None:
                    self.current = None
                elif self.current and self.current[0].version == reference.version:
                    self.current = (reference, self.current[1])
                else:
                    feed = await asyncio.to_thread(load_feed, reference)
                    self.current = (reference, feed)
                self.next_check = monotonic() + 60
            except Exception:
                # No credentials, database URLs, or upstream exceptions reach the public API.
                self.current = None
                self.next_check = monotonic() + 15
            return self.current


feed_provider = FeedProvider()
