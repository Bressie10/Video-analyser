"""Versioned, machine-readable technique vocabulary."""

import json
import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intelligence.versions import ONTOLOGY_VERSION

AREAS = frozenset({"hook", "format", "editing", "text", "structure", "audio", "cta", "visual"})
ID_PATTERN = re.compile(r"^(hook|format|editing|text|structure|audio|cta|visual)\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class Technique(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str
    temporal: bool
    observation_kind: str
    overlaps_allowed: bool
    introduced_in: str

    @model_validator(mode="after")
    def valid_metadata(self):
        if not ID_PATTERN.fullmatch(self.id) or self.category not in AREAS:
            raise ValueError("Invalid technique ID or category")
        if self.id.split(".", 1)[0] != self.category:
            raise ValueError("Technique ID must match category")
        if self.observation_kind not in {"point", "interval", "whole_video"}:
            raise ValueError("Invalid observation kind")
        if self.temporal != (self.observation_kind != "whole_video"):
            raise ValueError("Temporal flag must match observation kind")
        if self.introduced_in != ONTOLOGY_VERSION:
            raise ValueError("Unsupported ontology entry version")
        return self


@lru_cache(maxsize=1)
def techniques() -> dict[str, Technique]:
    data = json.loads(files("intelligence.ontology").joinpath("techniques.json").read_text())
    if data["ontology_version"] != ONTOLOGY_VERSION:
        raise ValueError("Unsupported ontology version")
    result = {}
    for raw in data["techniques"]:
        item = Technique.model_validate(raw)
        if item.id in result:
            raise ValueError(f"Duplicate technique ID: {item.id}")
        result[item.id] = item
    return result
