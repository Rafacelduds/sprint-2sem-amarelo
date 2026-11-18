from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bucket: str = Field(min_length=1)
    key: str = Field(pattern=r"^(raw|derived|manifests|backups|gtfs)/[^\s]+$")
    version_id: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stored_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    stored_size: int = Field(ge=0)
    encoding: Literal["identity", "gzip"] = "identity"
    content_type: str = "application/octet-stream"
    metadata: dict[str, str] = Field(default_factory=dict)


class ProcessingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    dataset: str = Field(min_length=1)
    period_start: datetime
    period_end: datetime
    code_version: str = Field(pattern=r"^[0-9a-f]{40}$")
    rule_version: str = Field(min_length=1)
    inputs: list[ObjectRef] = Field(min_length=1)
    outputs: list[ObjectRef] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_period(self) -> "ProcessingManifest":
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("período exige fuso horário")
        if self.period_end < self.period_start:
            raise ValueError("período invertido")
        return self
