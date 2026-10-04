"""Shared strict primitives for experimental intelligence documents."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intelligence.ontology import techniques

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


StructureRole = Literal[
    "hook", "setup", "problem", "explanation", "demonstration", "proof", "payoff", "cta", "other",
]


def require_version(actual: str, expected: str) -> str:
    if actual != expected:
        raise ValueError(f"Unsupported version {actual!r}; expected {expected!r}")
    return actual


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value


class TimeRange(Contract):
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float | None

    @model_validator(mode="after")
    def ordered(self):
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("End must be after start")
        return self


class TechniqueSpan(TimeRange):
    technique_id: str

    @model_validator(mode="after")
    def matches_ontology(self):
        technique = techniques().get(self.technique_id)
        if technique is None:
            raise ValueError(f"Unknown technique ID: {self.technique_id}")
        if (technique.observation_kind == "interval") != (self.end_seconds is not None):
            if technique.observation_kind != "whole_video":
                raise ValueError("Technique interval/point timing does not match ontology")
        if technique.observation_kind == "whole_video" and (self.start_seconds != 0 or self.end_seconds is not None):
            raise ValueError("Whole-video technique must start at zero and have no end")
        return self


class NumericFeature(Contract):
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1)
    window: TimeRange | None
    evidence_refs: list[str]

class SourceIdentity(Contract):
    source_kind: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    platform: str | None
    duration_seconds: float | None = Field(ge=0, allow_inf_nan=False)
