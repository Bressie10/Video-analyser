"""Apply the Stage 3.2 scene-only provisional truth repair offline."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .stage1_truth import validate_record

SCENE_REFS = {"04", "07", "09"}
PROVENANCE_NOTE = (
    "Stage 3.2 scene boundaries replaced from the full-video annotations supplied in the "
    "2026-10-11 conversation. The original other-signal reference was Gemini-generated "
    "and user-reviewed. This remains provisional calibration truth, not gold human truth; "
    "the scene reviewer had previously seen detector-related material, so this pass was "
    "not fully blinded. Source 07 ambiguous graphics are excluded from scored truth."
)


def repair(truth_dir: Path, backup_dir: Path, annotations_path: Path,
           durations: dict[str, float]) -> None:
    annotations = json.loads(annotations_path.read_text())
    if set(annotations) != SCENE_REFS:
        raise ValueError("Expected scene annotations for exactly 04, 07 and 09")
    originals = {path.name: path.read_bytes() for path in truth_dir.glob("*.json")}
    if len(originals) != 11 or not {f"{ref}.json" for ref in SCENE_REFS} <= set(originals):
        raise ValueError("Expected all 11 provisional truth records")
    updates = {}
    for ref in sorted(SCENE_REFS):
        annotation = annotations[ref]
        if set(annotation) != {"boundaries", "ambiguous"}:
            raise ValueError(f"Unexpected annotation fields: {ref}")
        boundaries = annotation["boundaries"]
        if not isinstance(boundaries, list) or any(
            not isinstance(row, dict) or set(row) != {"time_seconds"} for row in boundaries
        ):
            raise ValueError(f"Unexpected scene boundary fields: {ref}")
        record = json.loads(originals[f"{ref}.json"])
        record["observations"]["scene_boundaries"] = boundaries
        record["notes"] = record["notes"] + " " + PROVENANCE_NOTE
        validate_record(record, durations[ref], kind="reviewed")
        updates[ref] = record
    if backup_dir.exists():
        saved = {path.name: path.read_bytes() for path in backup_dir.glob("*.json")}
        if saved != originals:
            raise ValueError("Existing backup does not match current provisional truth")
    else:
        shutil.copytree(truth_dir, backup_dir)
    for ref, record in updates.items():
        (truth_dir / f"{ref}.json").write_text(json.dumps(record, indent=2) + "\n")
    for name in originals.keys() - {f"{ref}.json" for ref in SCENE_REFS}:
        if (truth_dir / name).read_bytes() != originals[name]:
            raise AssertionError(f"Unrelated truth changed: {name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    durations = {row["source_ref"]: row["duration_seconds"] for row in manifest["sources"]}
    repair(args.truth_dir, args.backup_dir, args.annotations, durations)


if __name__ == "__main__":
    main()
