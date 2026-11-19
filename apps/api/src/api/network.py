"""Versioned read-only map adapter for US02 archives or explicit test exports."""

import asyncio
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from api.config import get_settings
from api.live import live_positions
from api.network_gtfs import feed_provider

# SPTrans operating areas; screen RGB from the official routes.txt, inspected 2026-11-19.
AREA_COLORS = {
    1: ("Noroeste", "#509E2F"),
    2: ("Norte", "#002F6C"),
    3: ("Nordeste", "#FFD100"),
    4: ("Leste", "#DA291C"),
    5: ("Sudeste", "#006341"),
    6: ("Sul", "#0082BA"),
    7: ("Sudoeste", "#782F40"),
    8: ("Oeste", "#FF671F"),
    9: ("Central", "#969CA0"),
}


class NetworkLine(BaseModel):
    line_id: int
    label: str
    direction: int
    destination: str
    route_id: str
    direction_id: str
    area_id: int | None = Field(default=None, ge=1, le=9)
    area_source: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    color_source: str | None = None
    match_status: Literal["matched", "unmatched", "ambiguous"] = "matched"
    # Explicit matching evidence. sl and direction_id must not be assumed equivalent.
    match_source: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_area_source(self) -> "NetworkLine":
        if self.area_id is not None and not self.area_source:
            raise ValueError("Area association requires source")
        return self


class RouteGeometry(BaseModel):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[tuple[float, float]]]

    @field_validator("coordinates")
    @classmethod
    def check_coordinates(cls, value: list[list[tuple[float, float]]]):
        for segment in value:
            if len(segment) < 2:
                raise ValueError("At least two coordinates per segment")
            for lon, lat in segment:
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("Invalid coordinates")
        return value


class RouteFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: RouteGeometry
    properties: NetworkLine


class NetworkExport(BaseModel):
    version: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    captured_at: datetime
    source: str = Field(min_length=1)
    synthetic: bool = False
    features: list[RouteFeature]

    @model_validator(mode="after")
    def unique_lines(self) -> "NetworkExport":
        ids = [feature.properties.line_id for feature in self.features]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate Olho Vivo line/sense mapping")
        if self.captured_at.tzinfo is None:
            raise ValueError("Timezone required")
        return self


class CatalogLine(NetworkLine):
    pass


class Area(BaseModel):
    id: int
    name: str
    color: str


class NetworkCatalog(BaseModel):
    status: Literal["ready", "unavailable"]
    version: str | None = None
    captured_at: datetime | None = None
    source: str | None = None
    synthetic: bool = False
    areas: list[Area]
    lines: list[CatalogLine]


class RouteCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    version: str
    captured_at: datetime
    synthetic: bool
    features: list[RouteFeature]


@lru_cache(maxsize=2)
def read_export(path: str, modified: int, size: int) -> NetworkExport:
    del modified, size
    return NetworkExport.model_validate_json(Path(path).read_bytes())


def get_network() -> NetworkExport | None:
    path = get_settings().network_catalog_path
    if not path:
        return None
    try:
        stat = Path(path).stat()
        return read_export(path, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return None


async def current_network() -> NetworkExport | None:
    if get_settings().network_catalog_path:
        return await asyncio.to_thread(get_network)
    current = await feed_provider.get()
    if not current:
        return None
    reference, feed = current
    try:
        snapshot = await live_positions.get()
    except HTTPException:
        return NetworkExport(
            version=reference.version,
            captured_at=reference.captured_at,
            source=reference.source,
            features=[],
        )
    features: list[RouteFeature] = []
    for line in snapshot.lines:
        match = feed.match(line.label, line.destination)
        if not match:
            continue
        area = next(
            (
                id
                for id, (_, color) in AREA_COLORS.items()
                if id <= 8 and color == match.route.color
            ),
            None,
        )
        properties = NetworkLine(
            line_id=line.id,
            label=line.label,
            direction=line.direction,
            destination=line.destination,
            route_id=match.route.id,
            direction_id=match.direction,
            area_id=area,
            area_source="GTFS routes.txt/route_color + paleta oficial SPTrans" if area else None,
            color=match.route.color,
            color_source="GTFS routes.txt/route_color",
            match_source="route_short_name exato + trip_headsign normalizado único",
            match_status=match.status,
        )
        features.append(RouteFeature(properties=properties, geometry=RouteGeometry(coordinates=[])))
    return NetworkExport(
        version=reference.version,
        captured_at=reference.captured_at,
        source=reference.source,
        features=features,
    )


router = APIRouter(prefix="/network", tags=["rede e GTFS"])


@router.get("/catalog", response_model=NetworkCatalog)
async def catalog(response: Response) -> NetworkCatalog:
    response.headers["Cache-Control"] = "no-cache"
    network = await current_network()
    return NetworkCatalog(
        status="ready" if network else "unavailable",
        version=network.version if network else None,
        captured_at=network.captured_at if network else None,
        source=network.source if network else None,
        synthetic=network.synthetic if network else False,
        areas=[Area(id=key, name=name, color=color) for key, (name, color) in AREA_COLORS.items()],
        lines=[
            CatalogLine(
                **f.properties.model_dump(exclude={"color"}),
                color=(
                    f.properties.color
                    or (AREA_COLORS[f.properties.area_id][1] if f.properties.area_id else None)
                ),
            )
            for f in network.features
        ]
        if network
        else [],
    )


@router.get(
    "/routes/{line_id}",
    response_model=RouteCollection,
    responses={404: {"description": "Correspondência ou traçado indisponível"}},
)
async def route(line_id: int, response: Response, version: str | None = None) -> RouteCollection:
    network = await current_network()
    if not network or (version is not None and version != network.version):
        raise HTTPException(404, "Versão GTFS indisponível. Atualize o catálogo.")
    features = [f for f in network.features if f.properties.line_id == line_id]
    if features and not get_settings().network_catalog_path:
        current = await feed_provider.get()
        if current and current[0].version == network.version:
            feed = current[1]
            for feature in features:
                match = feed.match(feature.properties.label, feature.properties.destination)
                if match and match.status == "matched":
                    try:
                        coordinates = await asyncio.to_thread(feed.geometry, match.shapes)
                    except (OSError, sqlite3.Error):
                        coordinates = []
                    feature.geometry = RouteGeometry(coordinates=coordinates)
    if not features or not any(f.geometry.coordinates for f in features):
        raise HTTPException(404, "Percurso ainda não disponível para este sentido.")
    response.headers["Cache-Control"] = "no-cache"
    return RouteCollection(
        version=network.version,
        captured_at=network.captured_at,
        synthetic=network.synthetic,
        features=features,
    )
