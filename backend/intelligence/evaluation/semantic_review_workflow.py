"""Offline blind semantic review, disagreement, adjudication and gated comparison.

No inference or network calls. Reviewer-facing files are generated only from
the frozen ontology and controlled structure roles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intelligence.evaluation.stage5_1_review import _score, one_to_one
from intelligence.ontology import techniques
from intelligence.schemas.common import StructureRole
from intelligence.versions import ONTOLOGY_VERSION

REVIEW_VERSION = "v9-independent-review-1"
ADJUDICATION_VERSION = "v9-semantic-adjudication-1"
REFERENCE_VERSION = "v9-semantic-adjudicated-reference-1"
SOURCES = ("01", "04", "08", "12")
CATEGORIES = ("hook", "format", "editing", "text", "audio", "cta", "visual")
COVERAGE = ("complete", "partial", "unavailable")
STATUSES = ("present", "absent", "uncertain")
TOLERANCES = (0.25, 0.5, 1.0)


def render_blind_guide() -> str:
    """Use only frozen public contract data and generic instructions."""
    lines = ["# Independent semantic video review", "",
             f"Ontology version: **{ONTOLOGY_VERSION}**.", "",
             "Watch the complete assigned video with audio before annotating. Record what is",
             "actually visible or audible. Do not consult any prior annotation or analysis",
             "before submitting your review.", "",
             "## Annotation instructions", "",
             "- Make one reviewer JSON per reviewer per video. Fill every `null` in the template,",
             "  then validate it with the offline validator. Submit the file before discussing it",
             "  with another reviewer. Separate reviewer files must remain unchanged.",
             "- Record each technique or primary structure role with `present`, `absent`, or",
             "  `uncertain`, confidence from 0 to 1, and a short evidence note. Uncertainty is valid.",
             "  An omitted technique counts as absent only when its category coverage is `complete`.",
             "- Set category coverage independently for hook, format, editing, text, audio, CTA,",
             "  and visual, plus primary structure: `complete` means the full video and category",
             "  were assessed; `partial` means only some relevant material was assessable;",
             "  `unavailable` means it could not be assessed. Explain limitations in evidence notes.",
             "- Record reviewer ID or pseudonym, reviewer type, full-video and audio flags,",
             "  blind-review flag, whether you had previously seen ContentMetric outputs,",
             "  and a timezone-aware review timestamp. An earlier unrelated output exposure",
             "  should be disclosed even if this annotation was otherwise blind.",
             "- Use the frozen definitions below literally. `whole_video` is a video-level",
             "  property; the supporting action need not persist throughout the runtime unless",
             "  that definition itself requires substantial or main-format coverage.",
             "- A product or service shown in use can support `format.product_demo`. A visible",
             "  request, including request text, can support `cta.visual`. A request for a",
             "  product-related action such as a visit or purchase can support `cta.product`.",
             "- Record each physical CTA request once in `cta_events` and attach all independently",
             "  supported CTA ontology labels to that event. Multiple labels may describe one event.",
             "- Use one primary narrative structure role at a time. Different roles may touch",
             "  at a boundary but must not substantially overlap. Leave gaps when evidence is",
             "  insufficient; do not use `other` simply to fill a gap.", "",
             "## Timestamp conventions", "",
             "- Use seconds from the first video frame; intervals are `[start_seconds, end_seconds)`.",
             "  Record the earliest and latest supported boundaries, with `start < end`.",
             "- Point techniques use `start_seconds` and a null `end_seconds`. Whole-video",
             "  formats use null for both timestamps. An absent annotation has null timestamps.",
             "  An uncertain annotation may be left unlocalized with null timestamps.",
             "- Do not extend an interval through a gap on assumption alone. A claim seen in",
             "  one frame does not establish a continuous action between distant frames.",
             "- For audible techniques, listen to source audio. Spoken words shown as captions",
             "  establish visible text, while an audible request can separately support speech.", "",
             "## Generic examples", "",
             "- A clip showing a person operating a coffee grinder can support",
             "  `format.product_demo` even if that clip occupies only part of the video.",
             "- A card saying “Visit the store” can support `cta.visual` and `cta.product`",
             "  on one CTA event; an audible “Visit the store” can also support `cta.verbal`.",
             "- A narrator describing a recipe step, followed by a request to save the recipe,",
             "  may have an explanation interval followed by a CTA interval, with no overlap.", "",
             "### Illustrative JSON entry shapes", "",
             "Add records to the template arrays using these fields. These examples describe",
             "an imaginary coffee video and are not expected answers for any assigned source.", "",
             "```json", "{", "  \"items\": [",
             "    {\"technique_id\": \"format.product_demo\", \"status\": \"present\",",
             "     \"confidence\": 0.8, \"evidence_note\": \"A grinder is operated on screen.\",",
             "     \"start_seconds\": null, \"end_seconds\": null}", "  ],",
             "  \"cta_events\": [",
             "    {\"event_id\": \"request-1\", \"status\": \"present\", \"confidence\": 0.9,",
             "     \"evidence_note\": \"A card asks viewers to visit the store.\",",
             "     \"requested_action\": \"Visit the store\",",
             "     \"start_seconds\": 8.0, \"end_seconds\": 9.0,",
             "     \"labels\": [",
             "       {\"technique_id\": \"cta.visual\", \"status\": \"present\",",
             "        \"confidence\": 0.9, \"evidence_note\": \"The request is visible.\",",
             "        \"start_seconds\": 8.0, \"end_seconds\": 9.0}", "     ]}", "  ],",
             "  \"structure\": [",
             "    {\"role\": \"cta\", \"status\": \"present\", \"confidence\": 0.9,",
             "     \"evidence_note\": \"The closing segment requests a visit.\",",
             "     \"start_seconds\": 8.0, \"end_seconds\": 9.0}", "  ]", "}",
             "```", "",
             "## Controlled primary structure roles", "",
             ", ".join(f"`{role}`" for role in StructureRole.__args__), "",
             "## Frozen ontology definitions", ""]
    ontology = techniques()
    for category in (*CATEGORIES[:4], "structure", *CATEGORIES[4:]):
        lines += [f"### {category}", "", "| ID | Observation kind | Definition |", "| --- | --- | --- |"]
        lines += [f"| `{row.id}` | {row.observation_kind} | {row.description} |"
                  for row in ontology.values() if row.category == category]
        lines.append("")
    return "\n".join(lines)


def blank_reviewer_template(source_ref: str) -> dict:
    if source_ref not in SOURCES:
        raise ValueError("Unsupported pilot source")
    return {"review_version": REVIEW_VERSION, "ontology_version": ONTOLOGY_VERSION,
            "source_ref": source_ref, "duration_seconds": None,
            "provenance": {"reviewer_id": None, "reviewer_type": None,
                           "full_video_watched": None, "audio_heard": None,
                           "blind": None, "seen_contentmetric_outputs_previously": None,
                           "reviewed_at": None},
            "category_coverage": {category: None for category in CATEGORIES},
            "structure_coverage": None, "items": [], "cta_events": [], "structure": []}


def make_blind_package(output_dir: Path) -> None:
    _write_new(output_dir / "REVIEWER_GUIDE.md", render_blind_guide())
    for source_ref in SOURCES:
        _write_new(output_dir / "templates" / f"{source_ref}.json",
                   blank_reviewer_template(source_ref))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Annotation(StrictModel):
    technique_id: str
    status: Literal["present", "absent", "uncertain"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_note: str = Field(min_length=1)
    start_seconds: float | None = None
    end_seconds: float | None = None

    @model_validator(mode="after")
    def ontology_timing(self):
        technique = techniques().get(self.technique_id)
        if technique is None:
            raise ValueError(f"Unsupported ontology ID: {self.technique_id}")
        if not self.evidence_note.strip():
            raise ValueError("Evidence note is required")
        if self.status == "absent" and (self.start_seconds is not None or self.end_seconds is not None):
            raise ValueError("Absent annotation has no timestamp")
        if technique.observation_kind == "whole_video":
            if self.start_seconds is not None or self.end_seconds is not None:
                raise ValueError("Whole-video format has no interval")
        elif self.status == "present" or self.start_seconds is not None or self.end_seconds is not None:
            if self.start_seconds is None or self.start_seconds < 0:
                raise ValueError("Present or localized annotation needs a valid start")
            if technique.observation_kind == "point":
                if self.end_seconds is not None:
                    raise ValueError("Point technique cannot have an end")
            elif self.end_seconds is None or self.end_seconds <= self.start_seconds:
                raise ValueError("Interval technique needs a positive interval")
        return self


class CTAEvent(StrictModel):
    event_id: str = Field(min_length=1)
    status: Literal["present", "absent", "uncertain"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_note: str = Field(min_length=1)
    requested_action: str = Field(min_length=1)
    start_seconds: float | None = None
    end_seconds: float | None = None
    labels: list[Annotation]

    @model_validator(mode="after")
    def valid_event(self):
        if not self.event_id.strip() or not self.evidence_note.strip() or not self.requested_action.strip():
            raise ValueError("CTA event needs ID, request, and evidence")
        if self.status == "absent" and (self.start_seconds is not None or self.end_seconds is not None):
            raise ValueError("Absent CTA event has no timestamp")
        if self.status == "present" or self.start_seconds is not None or self.end_seconds is not None:
            if (self.start_seconds is None or self.end_seconds is None or
                    self.start_seconds < 0 or self.end_seconds <= self.start_seconds):
                raise ValueError("CTA event needs a positive interval")
        identifiers = [label.technique_id for label in self.labels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate CTA label on one physical event")
        for label in self.labels:
            if not label.technique_id.startswith("cta."):
                raise ValueError("CTA event labels must use CTA ontology IDs")
            if self.status != "present" and label.status == "present":
                raise ValueError("Only a present CTA event can have present labels")
            if (label.status == "present" and self.start_seconds is not None and
                    (label.start_seconds < self.start_seconds - .05 or
                     label.end_seconds > self.end_seconds + .05)):
                raise ValueError("CTA label must fit its physical event")
        return self


class StructureAnnotation(StrictModel):
    role: StructureRole
    status: Literal["present", "absent", "uncertain"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_note: str = Field(min_length=1)
    start_seconds: float | None = None
    end_seconds: float | None = None

    @model_validator(mode="after")
    def valid_timing(self):
        if not self.evidence_note.strip():
            raise ValueError("Structure evidence note is required")
        if self.status == "absent" and (self.start_seconds is not None or self.end_seconds is not None):
            raise ValueError("Absent structure role has no timestamp")
        if self.status == "present" or self.start_seconds is not None or self.end_seconds is not None:
            if (self.start_seconds is None or self.end_seconds is None or
                    self.start_seconds < 0 or self.end_seconds <= self.start_seconds):
                raise ValueError("Structure role needs a positive interval")
        return self


class AnnotationContent(StrictModel):
    source_ref: Literal["01", "04", "08", "12"]
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    category_coverage: dict[str, Literal["complete", "partial", "unavailable"]]
    structure_coverage: Literal["complete", "partial", "unavailable"]
    items: list[Annotation]
    cta_events: list[CTAEvent]
    structure: list[StructureAnnotation]

    @model_validator(mode="after")
    def complete_contract(self):
        if set(self.category_coverage) != set(CATEGORIES):
            raise ValueError("Coverage is required for every category")
        event_ids = [event.event_id for event in self.cta_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("CTA event IDs must be unique")
        for item in self.items:
            category = item.technique_id.split(".", 1)[0]
            if category == "cta":
                raise ValueError("CTA labels belong inside physical CTA events")
            if category not in self.category_coverage:
                raise ValueError("Unknown annotation category")
            if self.category_coverage[category] == "unavailable" and item.status == "present":
                raise ValueError("Unavailable category cannot contain a present finding")
            _within_duration(item, self.duration_seconds)
        if self.category_coverage["cta"] == "unavailable" and any(
                event.status == "present" for event in self.cta_events):
            raise ValueError("Unavailable CTA category cannot contain present events")
        for event in self.cta_events:
            _within_duration(event, self.duration_seconds)
            for label in event.labels:
                _within_duration(label, self.duration_seconds)
        if self.structure_coverage == "unavailable" and any(
                item.status == "present" for item in self.structure):
            raise ValueError("Unavailable structure cannot contain present roles")
        for item in self.structure:
            _within_duration(item, self.duration_seconds)
        present = [row for row in self.structure if row.status == "present"]
        for index, left in enumerate(present):
            for right in present[index + 1:]:
                if (left.role != right.role and
                        min(left.end_seconds, right.end_seconds) - max(
                            left.start_seconds, right.start_seconds) > .05):
                    raise ValueError("Incompatible primary structure roles overlap")
        return self


def _within_duration(row, duration: float) -> None:
    for value in (row.start_seconds, row.end_seconds):
        if value is not None and value > duration + .05:
            raise ValueError("Annotation timestamp exceeds video duration")


class ReviewerProvenance(StrictModel):
    reviewer_id: str = Field(min_length=1)
    reviewer_type: Literal["human", "other"]
    full_video_watched: bool
    audio_heard: bool
    blind: bool
    seen_contentmetric_outputs_previously: bool
    reviewed_at: datetime = Field(strict=False)

    @model_validator(mode="after")
    def valid_provenance(self):
        if not self.reviewer_id.strip() or self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Reviewer ID and timezone-aware review timestamp are required")
        return self


class ReviewerRecord(AnnotationContent):
    review_version: Literal["v9-independent-review-1"]
    ontology_version: Literal["1.1.0"]
    provenance: ReviewerProvenance

    @model_validator(mode="after")
    def observation_limits(self):
        if not self.provenance.audio_heard and self.category_coverage["audio"] != "unavailable":
            raise ValueError("Audio coverage must be unavailable if audio was not heard")
        if not self.provenance.full_video_watched and any(
                value == "complete" for value in (*self.category_coverage.values(), self.structure_coverage)):
            raise ValueError("Complete coverage requires watching the full video")
        return self


def load_review(path: Path, *, require_blind: bool = False) -> ReviewerRecord:
    record = ReviewerRecord.model_validate_json(path.read_text())
    if require_blind and not record.provenance.blind:
        raise ValueError("Independent review must be blind to existing annotations and predictions")
    return record


def _span(row) -> dict:
    return {"start_seconds": row.start_seconds, "end_seconds": row.end_seconds}


def _overlap(left, right) -> float:
    a, b = left.start_seconds, right.start_seconds
    ae, be = left.end_seconds, right.end_seconds
    if a is None or b is None:
        return 0.0
    if ae is None and be is None:
        return 1.0 if abs(a - b) <= .5 else 0.0
    if ae is None or be is None:
        point = a if ae is None else b
        interval_start = b if ae is None else a
        interval_end = be if ae is None else ae
        return 1.0 if interval_start <= point <= interval_end else 0.0
    intersection = max(0.0, min(ae, be) - max(a, b))
    union = max(ae, be) - min(a, b)
    return intersection / union if union else 0.0


def _status_by_id(record: ReviewerRecord) -> dict[str, str]:
    grouped = {}
    for item in [*record.items, *(label for event in record.cta_events for label in event.labels)]:
        grouped.setdefault(item.technique_id, []).append(item.status)
    result = {}
    for identifier, technique in techniques().items():
        category = technique.category
        if category == "structure":
            continue
        coverage = record.category_coverage[category]
        states = grouped.get(identifier, [])
        result[identifier] = ("present" if "present" in states else
                              "uncertain" if "uncertain" in states else
                              "absent" if "absent" in states or coverage == "complete" else
                              "unassessed")
    return result


def _present_items(record: ReviewerRecord, *, category: str | None = None) -> list[Annotation]:
    items = [*record.items, *(label for event in record.cta_events for label in event.labels)]
    return [item for item in items if item.status == "present" and
            (category is None or item.technique_id.startswith(category + "."))]


def _interval_disagreements(left: ReviewerRecord, right: ReviewerRecord) -> list[dict]:
    result = []
    identifiers = sorted(set(item.technique_id for item in _present_items(left)) |
                         set(item.technique_id for item in _present_items(right)))
    for identifier in identifiers:
        if techniques()[identifier].observation_kind == "whole_video":
            continue
        a = [item for item in _present_items(left) if item.technique_id == identifier]
        b = [item for item in _present_items(right) if item.technique_id == identifier]
        pairs = one_to_one(a, b, lambda x, y: _overlap(x, y) > .1)
        matched_a, matched_b = {i for i, _ in pairs}, {j for _, j in pairs}
        for i, j in pairs:
            if (abs(a[i].start_seconds - b[j].start_seconds) > .25 or
                    (a[i].end_seconds is not None and b[j].end_seconds is not None and
                     abs(a[i].end_seconds - b[j].end_seconds) > .25)):
                result.append({"technique_id": identifier, "kind": "boundary",
                               "left": _span(a[i]), "right": _span(b[j])})
        for i, item in enumerate(a):
            if i not in matched_a:
                result.append({"technique_id": identifier, "kind": "left_only_interval",
                               "left": _span(item)})
        for j, item in enumerate(b):
            if j not in matched_b:
                result.append({"technique_id": identifier, "kind": "right_only_interval",
                               "right": _span(item)})
    return result


def _event_disagreements(left: ReviewerRecord, right: ReviewerRecord) -> dict:
    a = [event for event in left.cta_events if event.status == "present"]
    b = [event for event in right.cta_events if event.status == "present"]
    pairs = one_to_one(a, b, lambda x, y: _overlap(x, y) > .1)
    matched_a, matched_b = {i for i, _ in pairs}, {j for _, j in pairs}
    paired = []
    for i, j in pairs:
        labels_a = sorted(label.technique_id for label in a[i].labels if label.status == "present")
        labels_b = sorted(label.technique_id for label in b[j].labels if label.status == "present")
        paired.append({"left_event_id": a[i].event_id, "right_event_id": b[j].event_id,
                       "left_interval": _span(a[i]), "right_interval": _span(b[j]),
                       "left_requested_action": a[i].requested_action,
                       "right_requested_action": b[j].requested_action,
                       "requested_action_disagreement": a[i].requested_action.strip().casefold() !=
                                                        b[j].requested_action.strip().casefold(),
                       "left_labels": labels_a, "right_labels": labels_b,
                       "label_disagreement": labels_a != labels_b,
                       "boundary_disagreement": abs(a[i].start_seconds - b[j].start_seconds) > .25 or
                       abs(a[i].end_seconds - b[j].end_seconds) > .25})
    return {"left_event_count": len(a), "right_event_count": len(b),
            "grouping_disagreement": len(a) != len(b) or len(pairs) != min(len(a), len(b)),
            "paired_events": paired,
            "left_only_events": [a[i].model_dump(mode="json") for i in range(len(a)) if i not in matched_a],
            "right_only_events": [b[j].model_dump(mode="json") for j in range(len(b)) if j not in matched_b]}


def _structure_disagreements(left: ReviewerRecord, right: ReviewerRecord) -> dict:
    a = [item for item in left.structure if item.status == "present"]
    b = [item for item in right.structure if item.status == "present"]
    pairs = one_to_one(a, b, lambda x, y: _overlap(x, y) > .1)
    matched_a, matched_b = {i for i, _ in pairs}, {j for _, j in pairs}
    return {"paired_intervals": [
                {"left": a[i].model_dump(mode="json"), "right": b[j].model_dump(mode="json"),
                 "role_disagreement": a[i].role != b[j].role,
                 "boundary_disagreement": abs(a[i].start_seconds - b[j].start_seconds) > .25 or
                 abs(a[i].end_seconds - b[j].end_seconds) > .25}
                for i, j in pairs],
            "left_only": [a[i].model_dump(mode="json") for i in range(len(a)) if i not in matched_a],
            "right_only": [b[j].model_dump(mode="json") for j in range(len(b)) if j not in matched_b]}


def compare_reviewers(left: ReviewerRecord, right: ReviewerRecord) -> dict:
    if left.source_ref != right.source_ref or abs(left.duration_seconds - right.duration_seconds) > .1:
        raise ValueError("Reviewer files describe different source videos or durations")
    if left.provenance.reviewer_id == right.provenance.reviewer_id:
        raise ValueError("Independent reviewers need distinct IDs")
    states_a, states_b = _status_by_id(left), _status_by_id(right)
    presence = [{"technique_id": identifier, "left": states_a[identifier], "right": states_b[identifier]}
                for identifier in states_a if states_a[identifier] != states_b[identifier]]
    coverage = [{"category": category, "left": left.category_coverage[category],
                 "right": right.category_coverage[category]}
                for category in CATEGORIES if left.category_coverage[category] != right.category_coverage[category]]
    if left.structure_coverage != right.structure_coverage:
        coverage.append({"category": "primary_structure", "left": left.structure_coverage,
                         "right": right.structure_coverage})
    return {"source_ref": left.source_ref,
            "reviewer_ids": [left.provenance.reviewer_id, right.provenance.reviewer_id],
            "category_coverage_disagreements": coverage,
            "label_presence_disagreements": presence,
            "whole_video_format_disagreements": [row for row in presence
                                                  if row["technique_id"].startswith("format.")],
            "interval_boundary_disagreements": _interval_disagreements(left, right),
            "cta_event_grouping_and_labels": _event_disagreements(left, right),
            "primary_structure_disagreements": _structure_disagreements(left, right)}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, document: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(document if isinstance(document, str) else json.dumps(document, indent=2) + "\n")


def prepare_adjudication(paths: list[Path], output: Path) -> dict:
    if not paths or len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("Provide one or more distinct reviewer files")
    records = [load_review(path, require_blind=True) for path in paths]
    if len({row.provenance.reviewer_id for row in records}) != len(records):
        raise ValueError("Reviewer IDs must be distinct")
    if any(row.source_ref != records[0].source_ref or
           abs(row.duration_seconds - records[0].duration_seconds) > .1 for row in records):
        raise ValueError("All reviewers must annotate the same source and duration")
    if any(not row.provenance.full_video_watched or not row.provenance.audio_heard for row in records):
        raise ValueError("Independent review requires the complete video with audio")
    human_count = sum(row.provenance.reviewer_type == "human" for row in records)
    if human_count == 0:
        raise ValueError("At least one independent human reviewer is required")
    document = {"adjudication_version": ADJUDICATION_VERSION,
                "source_ref": records[0].source_ref,
                "review_count": len(records),
                "human_reviewer_count": human_count,
                "fewer_than_two_human_reviewers": human_count < 2,
                "single_reviewer_limit": len(records) == 1,
                "reviewer_files": [{"reviewer_id": row.provenance.reviewer_id,
                                    "sha256": _sha(path), "filename": path.name,
                                    "reviewer_type": row.provenance.reviewer_type,
                                    "full_video_watched": row.provenance.full_video_watched,
                                    "audio_heard": row.provenance.audio_heard,
                                    "seen_contentmetric_outputs_previously":
                                        row.provenance.seen_contentmetric_outputs_previously}
                                   for row, path in zip(records, paths)],
                "pairwise_disagreements": [compare_reviewers(records[i], records[j])
                                           for i, j in combinations(range(len(records)), 2)],
                "adjudicator": None,
                "resolution_notes": [],
                "resolved_annotation": None}
    _write_new(output, document)
    return document


class Adjudicator(StrictModel):
    adjudicator_id: str = Field(min_length=1)
    reviewer_type: Literal["human", "other"]
    full_video_watched: bool
    audio_heard: bool
    adjudicated_at: datetime = Field(strict=False)

    @model_validator(mode="after")
    def valid_timestamp(self):
        if self.adjudicated_at.tzinfo is None or self.adjudicated_at.utcoffset() is None:
            raise ValueError("Adjudication timestamp needs a timezone")
        return self


def finalize_adjudication(template: Path, reviewer_paths: list[Path], output: Path) -> dict:
    source = json.loads(template.read_text())
    if source.get("adjudication_version") != ADJUDICATION_VERSION:
        raise ValueError("Unknown adjudication template version")
    if output.resolve() in {template.resolve(), *(path.resolve() for path in reviewer_paths)}:
        raise ValueError("Adjudicated reference must be a separate file")
    expected = {row["sha256"] for row in source["reviewer_files"]}
    if len(expected) != len(source["reviewer_files"]) or expected != {_sha(path) for path in reviewer_paths}:
        raise ValueError("Original reviewer file hashes changed")
    if len(reviewer_paths) != source["review_count"]:
        raise ValueError("Reviewer count changed")
    paths_by_hash = {_sha(path): path for path in reviewer_paths}
    records = [load_review(paths_by_hash[row["sha256"]], require_blind=True)
               for row in source["reviewer_files"]]
    if {row.provenance.reviewer_id for row in records} != {
            row["reviewer_id"] for row in source["reviewer_files"]}:
        raise ValueError("Reviewer identities changed")
    human_count = sum(row.provenance.reviewer_type == "human" for row in records)
    if (human_count != source.get("human_reviewer_count") or
            source.get("fewer_than_two_human_reviewers") != (human_count < 2) or
            source.get("single_reviewer_limit") != (len(records) == 1)):
        raise ValueError("Reviewer-count provenance changed")
    if source.get("pairwise_disagreements") != [
            compare_reviewers(records[i], records[j])
            for i, j in combinations(range(len(records)), 2)]:
        raise ValueError("Original reviewer disagreements changed")
    adjudicator = Adjudicator.model_validate(source.get("adjudicator"))
    notes = source.get("resolution_notes")
    if not isinstance(notes, list) or not notes or any(not isinstance(note, str) or not note.strip()
                                                      for note in notes):
        raise ValueError("Explicit nonempty adjudication notes are required")
    resolved = AnnotationContent.model_validate(source.get("resolved_annotation"))
    if resolved.source_ref != source["source_ref"] or abs(
            resolved.duration_seconds - records[0].duration_seconds) > .1:
        raise ValueError("Adjudicated source or duration changed")
    if any(adjudicator.adjudicated_at < row.provenance.reviewed_at for row in records):
        raise ValueError("Adjudication cannot precede original reviews")
    if not adjudicator.audio_heard and resolved.category_coverage["audio"] != "unavailable":
        raise ValueError("Adjudicator must hear audio to resolve audio coverage")
    if not adjudicator.full_video_watched and any(
            value == "complete" for value in (*resolved.category_coverage.values(), resolved.structure_coverage)):
        raise ValueError("Adjudicator must watch full video for complete coverage")
    document = {"reference_version": REFERENCE_VERSION,
                "reference_status": "adjudicated" if human_count >= 2 else
                                    "limited_human_review_adjudicated",
                "gold_truth": False,
                "review_count": len(records),
                "human_reviewer_count": human_count,
                "fewer_than_two_human_reviewers": human_count < 2,
                "single_reviewer_limit": len(records) == 1,
                "source_ref": resolved.source_ref,
                "reviewer_sha256": sorted(expected),
                "adjudicator": adjudicator.model_dump(mode="json"),
                "resolution_notes": notes,
                "annotation": resolved.model_dump(mode="json")}
    _write_new(output, document)
    return document


def load_reference(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("reference_version") != REFERENCE_VERSION or data.get("gold_truth") is not False:
        raise ValueError("An adjudicated reference is required before candidate comparison")
    if data.get("reference_status") not in ("adjudicated", "limited_human_review_adjudicated"):
        raise ValueError("Invalid adjudicated reference status")
    count = data.get("review_count")
    hashes = data.get("reviewer_sha256")
    if (not isinstance(count, int) or count < 1 or not isinstance(hashes, list) or
            len(hashes) != count or len(set(hashes)) != count or
            any(not isinstance(value, str) or len(value) != 64 or
                any(char not in "0123456789abcdef" for char in value) for value in hashes)):
        raise ValueError("Adjudicated reference needs distinct reviewer file hashes")
    human_count = data.get("human_reviewer_count")
    if (not isinstance(human_count, int) or not 1 <= human_count <= count or
            data.get("fewer_than_two_human_reviewers") != (human_count < 2) or
            data["reference_status"] != ("adjudicated" if human_count >= 2 else
                                         "limited_human_review_adjudicated") or
            data.get("single_reviewer_limit") != (count == 1)):
        raise ValueError("Reference status does not match reviewer count")
    Adjudicator.model_validate(data.get("adjudicator"))
    notes = data.get("resolution_notes")
    if not isinstance(notes, list) or not notes or any(
            not isinstance(note, str) or not note.strip() for note in notes):
        raise ValueError("Adjudicated reference needs explicit resolution notes")
    annotation = AnnotationContent.model_validate(data["annotation"])
    if annotation.source_ref != data.get("source_ref"):
        raise ValueError("Reference source mismatch")
    return data


def _truth_rows(annotation: AnnotationContent) -> list[dict]:
    result = []
    for item in [*annotation.items, *(label for event in annotation.cta_events
                                      for label in event.labels)]:
        category = item.technique_id.split(".", 1)[0]
        technique = techniques()[item.technique_id]
        start = 0.0 if technique.observation_kind == "whole_video" else item.start_seconds
        if start is None:
            start = 0.0  # Unlocalized uncertainty abstains on this label.
        result.append({"technique_id": item.technique_id, "status": item.status,
                       "coverage": annotation.category_coverage[category],
                       "start_seconds": start, "end_seconds": item.end_seconds,
                       "evidence_note": item.evidence_note})
    return result


def _candidate_events(candidate: dict) -> list[dict]:
    labels = {}
    for finding in candidate["synthesis_draft"]["findings"]:
        if finding["technique_id"].startswith("cta.") and finding.get("event_id"):
            labels.setdefault(finding["event_id"], []).append(finding["technique_id"])
    return [{"event_id": event["event_id"], "start_seconds": event["start_seconds"],
             "end_seconds": event["end_seconds"],
             "labels": sorted(labels.get(event["event_id"], []))}
            for event in candidate["cta_events"]]


def _cta_candidate_reference(candidate: dict, annotation: AnnotationContent) -> dict | None:
    if annotation.category_coverage["cta"] != "complete":
        return None
    predicted = _candidate_events(candidate)
    reviewed = [event for event in annotation.cta_events if event.status == "present"]
    def overlap(a, b):
        start = max(a["start_seconds"], b.start_seconds)
        end = min(a["end_seconds"], b.end_seconds)
        return max(0.0, end - start) > .1
    pairs = one_to_one(predicted, reviewed, overlap)
    matched_p, matched_r = {i for i, _ in pairs}, {j for _, j in pairs}
    return {"candidate_event_count": len(predicted), "reference_event_count": len(reviewed),
            "event_grouping_disagreement": len(predicted) != len(reviewed) or
                len(pairs) != min(len(predicted), len(reviewed)),
            "paired_events": [{"candidate_event_id": predicted[i]["event_id"],
                               "reference_event_id": reviewed[j].event_id,
                               "candidate_interval": {key: predicted[i][key] for key in
                                                      ("start_seconds", "end_seconds")},
                               "reference_interval": _span(reviewed[j]),
                               "candidate_labels": predicted[i]["labels"],
                               "reference_labels": sorted(label.technique_id for label in
                                                          reviewed[j].labels if label.status == "present"),
                               "reference_uncertain_labels": sorted(label.technique_id for label in
                                                                    reviewed[j].labels if label.status == "uncertain")}
                              for i, j in pairs],
            "candidate_only_events": [predicted[i] for i in range(len(predicted)) if i not in matched_p],
            "reference_only_events": [reviewed[j].model_dump(mode="json")
                                      for j in range(len(reviewed)) if j not in matched_r]}


def compare_candidate(candidate: dict, reference: dict) -> dict:
    annotation = AnnotationContent.model_validate(reference["annotation"])
    if candidate["source_ref"] != annotation.source_ref:
        raise ValueError("Candidate and adjudicated reference source mismatch")
    predictions = candidate["semantic_draft"]["findings"]
    expected = _truth_rows(annotation)
    labels = _score(predictions, expected, annotation.category_coverage, label_key="technique_id")
    intervals = {str(tolerance): _score(predictions, expected, annotation.category_coverage,
                                        label_key="technique_id", tolerance=tolerance)
                 for tolerance in TOLERANCES}
    structure = None
    if annotation.structure_coverage == "complete":
        truth_structure = [{"role": item.role, "status": item.status, "coverage": "complete",
                            "start_seconds": item.start_seconds or 0.0,
                            "end_seconds": item.end_seconds, "evidence_note": item.evidence_note}
                           for item in annotation.structure]
        structure = _score(candidate["semantic_draft"]["structure"], truth_structure,
                           {"structure": "complete"}, label_key="role")
    formats = None
    if annotation.category_coverage["format"] == "complete":
        present = {row["technique_id"] for row in expected
                   if row["technique_id"].startswith("format.") and row["status"] == "present"}
        uncertain = {row["technique_id"] for row in expected
                     if row["technique_id"].startswith("format.") and row["status"] == "uncertain"}
        predicted = {row["technique_id"] for row in predictions if row["technique_id"].startswith("format.")}
        formats = {"candidate_only": sorted(predicted - present - uncertain),
                   "reference_only": sorted(present - predicted),
                   "agreed_present": sorted(predicted & present),
                   "uncertain_reference": sorted(uncertain)}
    return {"source_ref": annotation.source_ref,
            "reference_version": reference["reference_version"],
            "reference_status": reference["reference_status"],
            "reference_review_count": reference["review_count"],
            "reference_human_reviewer_count": reference["human_reviewer_count"],
            "coverage": annotation.category_coverage,
            "structure_coverage": annotation.structure_coverage,
            "label": labels, "interval_matching": intervals,
            "structure_role_agreement": structure,
            "format_disagreements": formats,
            "cta_event_and_label_disagreements": _cta_candidate_reference(candidate, annotation),
            "unsupported_candidate_findings": [predictions[i] for i in labels["unsupported_prediction_indices"]],
            "missed_reference_findings": [expected[i] for i in labels["missed_reviewed_indices"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    package = commands.add_parser("make-blind-package", help="Export guide and blank templates only")
    package.add_argument("--output-dir", type=Path, required=True)
    validate = commands.add_parser("validate", help="Validate a submitted reviewer JSON file")
    validate.add_argument("review", type=Path)
    prepare = commands.add_parser("prepare-adjudication", help="Compare reviewers without resolving disagreements")
    prepare.add_argument("--reviews", nargs="+", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    finalize = commands.add_parser("finalize-adjudication", help="Validate a manually completed adjudication")
    finalize.add_argument("--template", type=Path, required=True)
    finalize.add_argument("--reviews", nargs="+", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare-frozen", help="Compare frozen Stage 5.4 after adjudication")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "make-blind-package":
        make_blind_package(args.output_dir)
        print("Created blind guide and four blank templates")
    elif args.command == "validate":
        record = load_review(args.review)
        print(f"Valid reviewer file: {record.source_ref} / {record.provenance.reviewer_id}")
    elif args.command == "prepare-adjudication":
        result = prepare_adjudication(args.reviews, args.output)
        print(f"Prepared {result['source_ref']} with {result['review_count']} reviewer(s)")
    elif args.command == "finalize-adjudication":
        result = finalize_adjudication(args.template, args.reviews, args.output)
        print(f"Created separate {result['reference_status']} reference for {result['source_ref']}")
    else:
        reference = load_reference(args.reference)  # Gate before reading candidate.
        if args.output.resolve() in {args.reference.resolve(), args.candidate.resolve()}:
            raise ValueError("Comparison output must be separate from inputs")
        candidate = json.loads(args.candidate.read_text())
        result = compare_candidate(candidate, reference)
        _write_new(args.output, result)
        print(f"Compared Stage 5.4 with adjudicated reference for {result['source_ref']}")


if __name__ == "__main__":
    main()
