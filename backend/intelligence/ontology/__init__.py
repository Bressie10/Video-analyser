"""Versioned, machine-readable technique vocabulary."""

import json
import re
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intelligence.versions import ONTOLOGY_VERSION

AREAS = frozenset({"hook", "format", "editing", "text", "structure", "audio", "cta", "visual"})
ID_PATTERN = re.compile(r"^(hook|format|editing|text|structure|audio|cta|visual)\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid ontology version: {value!r}")
    return tuple(map(int, match.groups()))


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
        version_tuple(self.introduced_in)
        return self


def validate_ontology(data: dict, *, expected_version: str) -> dict[str, Technique]:
    """Validate one explicit snapshot; no migration or future-version fallback."""
    if data["ontology_version"] != expected_version:
        raise ValueError("Unsupported ontology version")
    active = version_tuple(expected_version)
    result = {}
    for raw in data["techniques"]:
        item = Technique.model_validate(raw)
        if version_tuple(item.introduced_in) > active:
            raise ValueError(f"Technique introduced after ontology snapshot: {item.id}")
        if item.id in result:
            raise ValueError(f"Duplicate technique ID: {item.id}")
        result[item.id] = item
    return result


@lru_cache(maxsize=1)
def techniques() -> dict[str, Technique]:
    data = json.loads(files("intelligence.ontology").joinpath("techniques.json").read_text())
    return validate_ontology(data, expected_version=ONTOLOGY_VERSION)
