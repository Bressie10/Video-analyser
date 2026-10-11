"""Run the frozen Stage 5.4 inference on the seven remaining pilot sources."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from intelligence.evaluation.stage5_4_semantic import run_one

SOURCES = ("03", "05", "06", "07", "09", "10", "11")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-6-sol"))
    args = parser.parse_args()
    if len(args.sources) != len(set(args.sources)):
        parser.error("Duplicate source")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        parser.error("OPENAI_API_KEY is required")
    sources = {row["source_ref"]: row for row in json.loads(args.manifest.read_text())["sources"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    for ref in args.sources:
        output_path = args.output_dir / f"{ref}.json"
        if output_path.exists():
            print(f"{ref}: existing candidate retained", flush=True)
            continue
        result = json.loads((args.results / f"{ref}.json").read_text())
        media = Path(sources[ref]["media_path"])
        if not media.is_file():
            raise FileNotFoundError(f"Private source missing: {ref}")
        try:
            output = run_one(ref, media, result, model=args.model, api_key=key,
                             analyzer_commit=commit,
                             checkpoint_path=args.output_dir / f"{ref}.checkpoint.json")
        except ValueError as exc:
            (args.output_dir / f"{ref}.failure.json").write_text(json.dumps({
                "source_ref": ref, "validation_commit": commit,
                "error_type": type(exc).__name__, "error": str(exc),
                "checkpoint": f"{ref}.checkpoint.json"}, indent=2) + "\n")
            print(f"{ref}: validation failed: {exc}", flush=True)
            continue
        output_path.write_text(json.dumps(output, indent=2) + "\n")
        (args.output_dir / f"{ref}.ledger.json").write_text(json.dumps({
            "source_ref": ref, "analyzer_commit": output["analyzer_commit"],
            "validation_commit": commit,
            "model_passes": output["model_passes"][:-1], "chunk_plan": output["chunk_plan"],
            "evidence_ledger": output["evidence_ledger"]}, indent=2) + "\n")
        (args.output_dir / f"{ref}.failure.json").unlink(missing_ok=True)
        print(f"{ref}: {len(output['chunk_plan'])} chunks, "
              f"{len(output['semantic_draft']['findings'])} findings", flush=True)


if __name__ == "__main__":
    main()
