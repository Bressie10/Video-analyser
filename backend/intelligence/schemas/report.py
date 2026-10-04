"""Observed content facts only; no performance interpretation or advice."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from intelligence.schemas.common import (
    Contract, NumericFeature, SourceIdentity, StructureRole, TechniqueSpan, TimeRange, aware, require_version,
)
from intelligence.versions import ANALYSIS_REPORT_VERSION, ONTOLOGY_VERSION


class VersionedProducer(Contract):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Evidence(Contract):
    kind: Literal["transcript", "scene", "ocr", "motion", "frame", "audio", "human", "other"]
    reference: str = Field(min_length=1)
    detail: str | None


class TechniqueObservation(TechniqueSpan):
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    detector: VersionedProducer
    evidence: list[Evidence] = Field(min_length=1)


class StructureSegment(TimeRange):
    role: StructureRole
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    detector: VersionedProducer
    evidence: list[Evidence] = Field(min_length=1)


class ComputedFeature(NumericFeature):
    producer: VersionedProducer


class ProcessingProvenance(Contract):
    run_id: str = Field(min_length=1)
    processed_at: datetime
    pipeline_version: str = Field(min_length=1)
    input_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    _aware = field_validator("processed_at")(aware)


class AnalysisReport(Contract):
    schema_version: str
    ontology_version: str
    source: SourceIdentity
    producer_versions: list[VersionedProducer]
    techniques: list[TechniqueObservation]
    structure: list[StructureSegment]
    derived_features: list[ComputedFeature]
    limitations: list[str]
    provenance: ProcessingProvenance

    @field_validator("schema_version")
    @classmethod
    def report_version(cls, value: str) -> str:
        return require_version(value, ANALYSIS_REPORT_VERSION)

    @field_validator("ontology_version")
    @classmethod
    def ontology_version_supported(cls, value: str) -> str:
        return require_version(value, ONTOLOGY_VERSION)

    @model_validator(mode="after")
    def consistent(self):
        declared = {(d.name, d.version) for d in self.producer_versions}
        if len(declared) != len(self.producer_versions):
            raise ValueError("Duplicate producer version declaration")
        used = ([o.detector for o in self.techniques]
                + [s.detector for s in self.structure]
                + [f.producer for f in self.derived_features])
        if any((d.name, d.version) not in declared for d in used):
            raise ValueError("Observation or feature producer/version must be declared")
        duration = self.source.duration_seconds
        if duration is not None:
            spans = [*self.techniques, *self.structure]
            if any((s.end_seconds if s.end_seconds is not None else s.start_seconds) > duration for s in spans):
                raise ValueError("Observation extends beyond video duration")
        for feature in self.derived_features:
            if feature.window is not None:
                if feature.window.end_seconds is None:
                    raise ValueError("Feature window must have an end")
                if duration is not None and feature.window.end_seconds > duration:
                    raise ValueError("Feature window extends beyond video duration")
        return self
