"""Read-only adapter for a versioned US02 export; never downloads GTFS."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from api.config import get_settings

# SPTrans padrão cromático DV.01.001.1-2-R0. Screen approximations, not paint specs.
AREA_COLORS = {
    1: ("Noroeste", "#638D36"),
    2: ("Norte", "#22599B"),
    3: ("Nordeste", "#E4B621"),
    4: ("Leste", "#D5453D"),
    5: ("Sudeste", "#28704C"),
    6: ("Sul", "#42A6CC"),
    7: ("Sudoeste", "#8C3C59"),
    8: ("Oeste", "#DE7D30"),
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
    color: str | None = None


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


router = APIRouter(prefix="/network", tags=["rede e GTFS"])


@router.get("/catalog", response_model=NetworkCatalog)
def catalog(response: Response) -> NetworkCatalog:
    response.headers["Cache-Control"] = "no-cache"
    network = get_network()
    return NetworkCatalog(
        status="ready" if network else "unavailable",
        version=network.version if network else None,
        captured_at=network.captured_at if network else None,
        source=network.source if network else None,
        synthetic=network.synthetic if network else False,
        areas=[Area(id=key, name=name, color=color) for key, (name, color) in AREA_COLORS.items()],
        lines=[
            CatalogLine(
                **f.properties.model_dump(),
                color=(AREA_COLORS[f.properties.area_id][1] if f.properties.area_id else None),
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
def route(line_id: int, response: Response, version: str | None = None) -> RouteCollection:
    network = get_network()
    if not network or (version is not None and version != network.version):
        raise HTTPException(404, "Versão GTFS indisponível. Atualize o catálogo.")
    features = [f for f in network.features if f.properties.line_id == line_id]
    if not features or not any(f.geometry.coordinates for f in features):
        raise HTTPException(404, "Percurso ainda não disponível para este sentido.")
    response.headers["Cache-Control"] = "no-cache"
    return RouteCollection(
        version=network.version,
        captured_at=network.captured_at,
        synthetic=network.synthetic,
        features=features,
    )
