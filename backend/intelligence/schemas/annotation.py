"""Human-labelled source records with explicit negative-label scope."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from intelligence.ontology import AREAS
from intelligence.schemas.common import (
    Contract, NumericFeature, SourceIdentity, StructureRole, TechniqueSpan,
    TimeRange, aware, require_version,
)
from intelligence.versions import ANNOTATION_VERSION, ONTOLOGY_VERSION


class HumanTechnique(TechniqueSpan):
    note: str | None


class HumanStructure(TimeRange):
    role: StructureRole
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    note: str | None


class NumericFieldCoverage(Contract):
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    status: Literal["measured", "unavailable", "not_applicable"]
    note: str | None

    @model_validator(mode="after")
    def explain_missing(self):
        if self.status != "measured" and not (self.note and self.note.strip()):
            raise ValueError("Unavailable or inapplicable numeric field needs a note")
        return self


class AnnotationCoverage(Contract):
    complete_technique_categories: list[str]
    structure_complete: bool
    numeric_fields: list[NumericFieldCoverage]

    @model_validator(mode="after")
    def unique_scopes(self):
        categories = self.complete_technique_categories
        if any(category not in AREAS for category in categories) or len(categories) != len(set(categories)):
            raise ValueError("Technique coverage categories must be unique ontology categories")
        ids = [field.feature_id for field in self.numeric_fields]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate numeric coverage field")
        return self


class Annotation(Contract):
    schema_version: str
    ontology_version: str
    annotation_ref: str = Field(min_length=1)
    annotator_ref: str = Field(min_length=1)
    guideline_version: str = Field(min_length=1)
    annotated_at: datetime
    source: SourceIdentity
    coverage: AnnotationCoverage
    techniques: list[HumanTechnique]
    structure: list[HumanStructure]
    numeric_ground_truth: list[NumericFeature]
    notes: str | None

    _aware = field_validator("annotated_at")(aware)

    @field_validator("schema_version")
    @classmethod
    def schema_supported(cls, value: str) -> str:
        return require_version(value, ANNOTATION_VERSION)

    @field_validator("ontology_version")
    @classmethod
    def ontology_supported(cls, value: str) -> str:
        return require_version(value, ONTOLOGY_VERSION)

    @model_validator(mode="after")
    def within_source(self):
        duration = self.source.duration_seconds
        if duration is not None and any(
            (span.end_seconds if span.end_seconds is not None else span.start_seconds) > duration
            for span in [*self.techniques, *self.structure]
        ):
            raise ValueError("Annotation extends beyond video duration")
        for feature in self.numeric_ground_truth:
            if feature.window is not None:
                if feature.window.end_seconds is None:
                    raise ValueError("Ground-truth window must have an end")
                if duration is not None and feature.window.end_seconds > duration:
                    raise ValueError("Ground-truth window extends beyond video duration")
        measured = {field.feature_id for field in self.coverage.numeric_fields
                    if field.status == "measured"}
        values = [feature.feature_id for feature in self.numeric_ground_truth]
        if len(values) != len(set(values)) or measured != set(values):
            raise ValueError("Measured numeric coverage must match ground-truth values exactly")
        return self


class SourceSplit(Contract):
    source_ref: str = Field(min_length=1)
    partition: Literal["train", "validation", "test"]
    group_ref: str | None

    @field_validator("group_ref")
    @classmethod
    def nonblank_group(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Group reference must be nonblank")
        return value


class AnnotationDataset(Contract):
    annotations: list[Annotation]
    split_assignments: list[SourceSplit] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self):
        refs = [a.annotation_ref for a in self.annotations]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate annotation reference")
        sources = {}
        for annotation in self.annotations:
            ref = annotation.source.reference_id
            if ref in sources and sources[ref] != annotation.source:
                raise ValueError("Annotations sharing a source reference have inconsistent identity")
            sources[ref] = annotation.source
        if self.split_assignments:
            assignments = {item.source_ref: item for item in self.split_assignments}
            if len(assignments) != len(self.split_assignments) or set(assignments) != set(sources):
                raise ValueError("Exactly one split assignment is required per source")
            groups = {}
            for item in self.split_assignments:
                if item.group_ref is not None:
                    if item.group_ref in groups and groups[item.group_ref] != item.partition:
                        raise ValueError("Grouped sources cannot cross partitions")
                    groups[item.group_ref] = item.partition
        return self
