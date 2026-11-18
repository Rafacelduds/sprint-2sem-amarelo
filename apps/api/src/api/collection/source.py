"""Adaptador Olho Vivo. Nunca propagar URLs de autenticação em erros/logs."""

import json
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class SourceError(Exception):
    """Falha da origem, sem credenciais na mensagem."""


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p: str | int | None = None
    ta: datetime | None = None
    py: float | None = None
    px: float | None = None


class Line(BaseModel):
    c: str | None = None
    cl: int | None = None
    sl: int | None = None
    vs: list[Vehicle]


class Company(BaseModel):
    c: int


class Area(BaseModel):
    e: list[Company]


class Companies(BaseModel):
    e: list[Area]


class Positions(BaseModel):
    lines: list[Line] = Field(alias="l")


class Snapshot(BaseModel):
    endpoint: str
    company: int | None = None
    collected_at: datetime
    body: bytes
    positions: Positions


class OlhoVivo:
    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.token = token
        self.authenticated = False
        self.companies: list[int] | None = None

    async def authenticate(self) -> None:
        try:
            response = await self.client.post("/Login/Autenticar", params={"token": self.token})
            response.raise_for_status()
            if response.json() is not True:
                raise SourceError("authentication_rejected")
        except (httpx.HTTPError, ValueError):
            raise SourceError("authentication_failed") from None
        self.authenticated = True

    async def get(self, endpoint: str, params: dict[str, int] | None = None) -> httpx.Response:
        if not self.authenticated:
            await self.authenticate()
        try:
            response = await self.client.get(endpoint, params=params)
            if response.status_code in (401, 403):
                self.authenticated = False
                raise SourceError("session_expired")
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise SourceError(f"{endpoint}:http_{exc.response.status_code}") from None
        except httpx.HTTPError:
            raise SourceError(f"{endpoint}:transport_failure") from None

    async def company_codes(self) -> list[int]:
        if self.companies is not None:
            return self.companies
        response = await self.get("/Empresa")
        try:
            data = TypeAdapter(list[Companies] | Companies).validate_json(response.content)
            roots = data if isinstance(data, list) else [data]
            codes = sorted({e.c for root in roots for area in root.e for e in area.e})
            if not codes:
                raise ValueError("empty companies")
        except (ValueError, TypeError, KeyError):
            raise SourceError("invalid_companies") from None
        self.companies = codes
        return codes

    async def snapshot(self, company: int | None = None) -> Snapshot:
        endpoint = "/Posicao" if company is None else "/Posicao/Garagem"
        response = await self.get(endpoint, None if company is None else {"codigoEmpresa": company})
        collected_at = datetime.now(UTC)
        try:
            positions = Positions.model_validate_json(response.content)
            # A missing timestamp is null; a timestamp without timezone is not usable as UTC.
            for line in positions.lines:
                for vehicle in line.vs:
                    if vehicle.ta is not None and vehicle.ta.tzinfo is None:
                        raise ValueError("naive GPS timestamp")
            return Snapshot(
                endpoint=endpoint,
                company=company,
                collected_at=collected_at,
                body=response.content,
                positions=positions,
            )
        except (ValidationError, ValueError, json.JSONDecodeError):
            raise SourceError("invalid_positions") from None
