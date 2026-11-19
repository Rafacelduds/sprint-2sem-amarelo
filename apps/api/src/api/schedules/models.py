import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DAY_TYPES = {"U": 0, "S": 1, "D": 2}


def seconds(value: str) -> int:
    if not re.fullmatch(r"\d{2,3}:[0-5]\d(?::[0-5]\d)?", value):
        raise ValueError("horário inválido")
    parts = [int(part) for part in value.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) == 3 else 0)


class ScheduledTime(BaseModel):
    horario: str


class Band(BaseModel):
    tipoDia: Literal[0, 1, 2]
    faixaHoraria: int = Field(ge=0, le=47)
    totalPartidas: int = Field(ge=0)
    horariosProgramados: list[ScheduledTime]

    @model_validator(mode="after")
    def valid_times(self) -> "Band":
        for item in self.horariosProgramados:
            seconds(item.horario)
        return self


class OfficialLine(BaseModel):
    codigoLinha: str
    partidasIda: list[Band]
    partidasVolta: list[Band]


class CatalogLine(BaseModel):
    codigo: str
    CdPjOID: int


@dataclass(frozen=True)
class Departure:
    line: str
    direction: str
    direction_system: str
    service_date: date
    departure_seconds: int
    kind: str
    source_sha256: str
    trip_id: str | None = None
    source_order: int = 0


def official_departures(
    detail: OfficialLine, line: str, service_date: date, day_type: str, sha256: str
) -> tuple[list[Departure], dict[str, int]]:
    if detail.codigoLinha.strip() != line:
        raise ValueError("linha retornada diverge da linha solicitada")
    departures: list[Departure] = []
    expected: dict[str, int] = {}
    found_day = False
    for direction, bands in (("0", detail.partidasIda), ("1", detail.partidasVolta)):
        selected = [band for band in bands if band.tipoDia == DAY_TYPES[day_type]]
        found_day |= bool(selected)
        expected[direction] = sum(band.totalPartidas for band in selected)
        for band in selected:
            for item in band.horariosProgramados:
                # A fonte fornece hora civil e ordem, sem definir o corte operacional.
                # Preservar 00:xx sem inferir que significa 24:xx.
                departures.append(
                    Departure(
                        line,
                        direction,
                        "sptrans_itinerarios",
                        service_date,
                        seconds(item.horario),
                        "official",
                        sha256,
                        source_order=len(departures),
                    )
                )
    if not found_day:
        raise ValueError("fonte sem programação explícita para o tipo de dia")
    return departures, expected
