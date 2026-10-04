"""Human-labelled source records; independent annotations may share a source."""

from pydantic import Field, field_validator, model_validator

from intelligence.schemas.common import Contract, NumericFeature, SourceIdentity, StructureRole, TechniqueSpan, TimeRange, require_version
from intelligence.versions import ANNOTATION_VERSION, ONTOLOGY_VERSION


class HumanTechnique(TechniqueSpan):
    note: str | None


class HumanStructure(TimeRange):
    role: StructureRole
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    note: str | None


class Annotation(Contract):
    schema_version: str
    ontology_version: str
    annotation_ref: str = Field(min_length=1)
    annotator_ref: str = Field(min_length=1)
    source: SourceIdentity
    techniques: list[HumanTechnique]
    structure: list[HumanStructure]
    numeric_ground_truth: list[NumericFeature]
    notes: str | None

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
        return self


class AnnotationDataset(Contract):
    annotations: list[Annotation]

    @model_validator(mode="after")
    def unique_references(self):
        refs = [a.annotation_ref for a in self.annotations]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate annotation reference")
        return self
