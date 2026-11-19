"""Public live-map snapshot. No historical collection or persistence (US01)."""

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError

from api.config import get_settings


class Vehicle(BaseModel):
    id: str
    line_id: int
    line: str
    direction: int
    destination: str
    latitude: float
    longitude: float
    gps_at: datetime | None
    accessible: bool | None


class Line(BaseModel):
    id: int
    label: str
    direction: int
    destination: str


class Snapshot(BaseModel):
    collected_at: datetime
    served_at: datetime
    source: Literal["SPTrans / Olho Vivo"] = "SPTrans / Olho Vivo"
    stale: bool = False
    vehicles: list[Vehicle]
    lines: list[Line]
    discarded: int = 0


class RawVehicle(BaseModel):
    p: str | int
    py: float = Field(ge=-90, le=90, allow_inf_nan=False)
    px: float = Field(ge=-180, le=180, allow_inf_nan=False)
    ta: datetime | None = None
    a: bool | None = None


class RawLine(BaseModel):
    cl: int
    c: str
    sl: int
    lt0: str = ""
    lt1: str = ""
    vs: list[object]


class RawPositions(BaseModel):
    lines: list[object] = Field(alias="l")


def normalize(payload: object, collected_at: datetime) -> Snapshot:
    positions = RawPositions.model_validate(payload)
    vehicles: dict[str, Vehicle] = {}
    lines: dict[int, Line] = {}
    discarded = 0
    for item in positions.lines:
        try:
            line = RawLine.model_validate(item)
        except ValidationError:
            discarded += 1
            continue
        # Posicao repeats both directional headsigns (lt0/tp and lt1/ts) for each sl.
        # Choose the direction's headsign before matching GTFS; never map sl to direction_id.
        destination = line.lt0 if line.sl == 1 else line.lt1 if line.sl == 2 else ""
        lines[line.cl] = Line(id=line.cl, label=line.c, direction=line.sl, destination=destination)
        for raw in line.vs:
            try:
                bus = RawVehicle.model_validate(raw)
                if bus.py == 0 and bus.px == 0:
                    raise ValueError("Invalid origin")
                if bus.ta and bus.ta.tzinfo is None:
                    raise ValueError("GPS time without timezone")
            except (ValidationError, ValueError):
                discarded += 1
                continue
            vehicles[str(bus.p)] = Vehicle(
                id=str(bus.p),
                line_id=line.cl,
                line=line.c,
                direction=line.sl,
                destination=destination,
                latitude=bus.py,
                longitude=bus.px,
                gps_at=bus.ta,
                accessible=bus.a,
            )
    return Snapshot(
        collected_at=collected_at,
        served_at=collected_at,
        vehicles=list(vehicles.values()),
        lines=sorted(lines.values(), key=lambda line: (line.label, line.direction)),
        discarded=discarded,
    )


class LivePositions:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.snapshot: Snapshot | None = None
        self.next_attempt = 0.0

    async def fetch(self) -> Snapshot:
        settings = get_settings()
        token = settings.olho_vivo_token.get_secret_value()
        if not token:
            raise HTTPException(503, "A fonte de posições ainda não está configurada.")
        async with httpx.AsyncClient(
            base_url=settings.olho_vivo_base_url,
            timeout=8.0,
        ) as client:
            auth = await client.post("/Login/Autenticar", params={"token": token})
            auth.raise_for_status()
            if auth.json() is not True:
                raise ValueError("Authentication refused")
            response = await client.get("/Posicao")
            response.raise_for_status()
            return normalize(response.json(), datetime.now(UTC))

    async def get(self) -> Snapshot:
        async with self.lock:
            if monotonic() >= self.next_attempt:
                try:
                    self.snapshot = await self.fetch()
                except (httpx.HTTPError, ValueError, HTTPException):
                    if self.snapshot is None:
                        raise HTTPException(
                            503, "Posições indisponíveis. Tente novamente."
                        ) from None
                finally:
                    # Coalesce requests and back off after failures; no per-user polling upstream.
                    self.next_attempt = monotonic() + 15
            if self.snapshot is None:
                raise HTTPException(503, "Posições indisponíveis. Tente novamente.")
            now = datetime.now(UTC)
            return self.snapshot.model_copy(
                update={
                    "served_at": now,
                    "stale": (now - self.snapshot.collected_at).total_seconds() > 60,
                }
            )


live_positions = LivePositions()
router = APIRouter(prefix="/vehicles", tags=["mapa ao vivo"])


@router.get(
    "/positions",
    response_model=Snapshot,
    responses={503: {"description": "Fonte indisponível e sem snapshot anterior"}},
    description="Snapshot público; collected_at é a coleta, gps_at é a emissão do GPS. "
    "Snapshot com mais de 60 segundos é marcado stale e não deve ser exibido como ao vivo.",
)
async def positions(response: Response, line_id: int | None = Query(default=None)) -> Snapshot:
    snapshot = await live_positions.get()
    response.headers["Cache-Control"] = "no-store"
    if line_id is not None:
        snapshot = snapshot.model_copy(
            update={
                "vehicles": [bus for bus in snapshot.vehicles if bus.line_id == line_id],
            }
        )
    return snapshot
