"""Reference video context and snapshots; no acquisition or scoring policy."""

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from intelligence.schemas.common import Contract, aware, require_version
from intelligence.versions import ANALYSIS_REPORT_VERSION, BENCHMARK_VERSION, ONTOLOGY_VERSION


def valid_metrics(values: dict[str, int | float | None]) -> dict[str, int | float | None]:
    if any(not key.strip() for key in values):
        raise ValueError("Metric keys must be non-empty")
    if any(value is not None and (value < 0 or
           (isinstance(value, float) and not math.isfinite(value))) for value in values.values()):
        raise ValueError("Metrics must be finite non-negative values or null")
    return values


class MetricDefinition(Contract):
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    measurement_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonblank(self):
        if not all(value.strip() for value in (
            self.description, self.unit, self.measurement_basis,
        )):
            raise ValueError("Metric definition fields must be nonblank")
        return self


def require_definitions(metrics: dict, definitions: dict) -> None:
    if set(metrics) != set(definitions):
        raise ValueError("Every recorded metric key needs exactly one semantic definition")


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
    metric_definitions: dict[str, MetricDefinition]
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
        require_definitions(self.metrics, self.metric_definitions)
        if self.observation_window_start and self.observation_window_end:
            if self.observation_window_end < self.observation_window_start:
                raise ValueError("Invalid performance observation window")
        return self


class AccountBaseline(Contract):
    source: str = Field(min_length=1)
    metrics: dict[str, int | float | None]
    metric_definitions: dict[str, MetricDefinition]
    sample_size: int = Field(ge=1)
    window_start: datetime
    window_end: datetime
    cohort_definition: str = Field(min_length=1)
    method_reference: str = Field(min_length=1)

    _valid_metrics = field_validator("metrics")(valid_metrics)

    @field_validator("window_start", "window_end")
    @classmethod
    def window_aware(cls, value):
        return aware(value)

    @model_validator(mode="after")
    def ordered_window(self):
        require_definitions(self.metrics, self.metric_definitions)
        if not self.source.strip() or not self.cohort_definition.strip() or not self.method_reference.strip():
            raise ValueError("Baseline source, cohort and method must be nonblank")
        if self.window_end <= self.window_start:
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
