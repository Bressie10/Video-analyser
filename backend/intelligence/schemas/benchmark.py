"""Reference video context and snapshots; no acquisition or scoring policy."""

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from intelligence.schemas.common import Contract, aware, require_version
from intelligence.versions import ANALYSIS_REPORT_VERSION, BENCHMARK_VERSION, ONTOLOGY_VERSION


def valid_metrics(values: dict[str, int | float | None]) -> dict[str, int | float | None]:
    if any(value is not None and (value < 0 or not math.isfinite(value)) for value in values.values()):
        raise ValueError("Metrics must be finite non-negative values or null")
    return values


class SourceProvenance(Contract):
    platform: str = Field(min_length=1)
    provider_identifier: str | None
    public_url: str | None
    reference: str = Field(min_length=1)
    acquisition_method: str = Field(min_length=1)
    fetched_at: datetime

    _aware = field_validator("fetched_at")(aware)

    @model_validator(mode="after")
    def identifiable(self):
        if self.provider_identifier is None and self.public_url is None:
            raise ValueError("Provider ID or public URL is required")
        return self


class CreatorContext(Contract):
    account_identifier: str | None
    account_url: str | None
    follower_count: int | None = Field(ge=0)
    follower_count_observed_at: datetime | None

    @field_validator("follower_count_observed_at")
    @classmethod
    def observed_at_aware(cls, value):
        return aware(value) if value is not None else value

    @model_validator(mode="after")
    def follower_snapshot(self):
        if (self.follower_count is None) != (self.follower_count_observed_at is None):
            raise ValueError("Follower count and observation time must be supplied together")
        return self


class PublicationContext(Contract):
    published_at: datetime | None
    content_type: str | None
    declared_format: str | None

    @field_validator("published_at")
    @classmethod
    def published_at_aware(cls, value):
        return aware(value) if value is not None else value


class PerformanceSnapshot(Contract):
    fetched_at: datetime
    source: str = Field(min_length=1)
    exposure: Literal["organic", "paid", "mixed", "unknown"]
    metrics: dict[str, int | float | None]
    metric_definitions: dict[str, str]
    observation_window_start: datetime | None
    observation_window_end: datetime | None
    attribution_context: str | None

    _aware = field_validator("fetched_at")(aware)

    @field_validator("observation_window_start", "observation_window_end")
    @classmethod
    def window_aware(cls, value):
        return aware(value) if value is not None else value

    _valid_metrics = field_validator("metrics")(valid_metrics)

    @model_validator(mode="after")
    def ordered_window(self):
        if self.observation_window_start and self.observation_window_end:
            if self.observation_window_end < self.observation_window_start:
                raise ValueError("Invalid performance observation window")
        return self


class AccountBaseline(Contract):
    metrics: dict[str, int | float | None]
    sample_size: int | None = Field(ge=0)
    window_start: datetime | None
    window_end: datetime | None
    method_reference: str | None

    _valid_metrics = field_validator("metrics")(valid_metrics)

    @field_validator("window_start", "window_end")
    @classmethod
    def window_aware(cls, value):
        return aware(value) if value is not None else value

    @model_validator(mode="after")
    def ordered_window(self):
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("Invalid baseline window")
        return self


class AnalysisReference(Contract):
    report_ref: str = Field(min_length=1)
    report_schema_version: str
    ontology_version: str

    @field_validator("report_schema_version")
    @classmethod
    def report_supported(cls, value: str) -> str:
        return require_version(value, ANALYSIS_REPORT_VERSION)

    @field_validator("ontology_version")
    @classmethod
    def ontology_supported(cls, value: str) -> str:
        return require_version(value, ONTOLOGY_VERSION)


class BenchmarkVideo(Contract):
    schema_version: str
    source: SourceProvenance
    creator: CreatorContext
    publication: PublicationContext
    performance: PerformanceSnapshot | None
    analysis: AnalysisReference | None
    baseline: AccountBaseline | None
    provenance_notes: list[str]

    @field_validator("schema_version")
    @classmethod
    def schema_supported(cls, value: str) -> str:
        return require_version(value, BENCHMARK_VERSION)
