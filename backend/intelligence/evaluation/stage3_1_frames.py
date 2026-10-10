"""Extract private frame evidence for threshold-27 unmatched scene predictions only."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .stage1 import _hash, _private_path, load_manifest
from .stage3_1_audit import OFFSETS, REFS


def extract(manifest_path: Path, sweep_path: Path, output_dir: Path,
            *, refs=REFS, normalise=None) -> dict:
    """Normalise once per source and sample decoded frames; run no detectors."""
    import cv2
    import numpy as np

    if normalise is None:
        from app.video_processing import normalise_video
        normalise = normalise_video
    manifest = load_manifest(manifest_path)
    sweep = json.loads(sweep_path.read_text())
    output_dir = _private_path(output_dir)
    items = {item["source_ref"]: item for item in manifest["sources"]}
    results = {}
    for ref in refs:
        if ref not in REFS or ref not in items:
            raise ValueError(f"Unsupported audit source: {ref}")
        source = _private_path(Path(items[ref]["media_path"]))
        if _hash(source) != sweep["sources"][ref]["source_sha256"]:
            raise ValueError(f"Source identity mismatch: {ref}")
        times = sweep["sources"][ref]["thresholds"]["27"]["scores"]["0.5"]
        cuts = times["unmatched_prediction_seconds"]
        target = output_dir / ref
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite private evidence: {target}")
        target.mkdir(parents=True)
        with tempfile.TemporaryDirectory(prefix="cm-stage3-1-") as work:
            normalized = Path(work) / "normalised.mp4"
            normalise(source, normalized)
            cap = cv2.VideoCapture(str(normalized))
            if not cap.isOpened():
                raise RuntimeError(f"Could not decode normalised video: {ref}")
            rows = []
            try:
                for index, cut in enumerate(cuts, 1):
                    frames = []
                    for offset in OFFSETS:
                        timestamp = max(0, cut + offset)
                        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                        ok, frame = cap.read()
                        if not ok:
                            raise RuntimeError(f"Could not decode frame: {ref} {timestamp}")
                        name = f"{index:03d}_{offset:+.2f}.jpg"
                        if not cv2.imwrite(str(target / name), frame,
                                           [cv2.IMWRITE_JPEG_QUALITY, 90]):
                            raise RuntimeError(f"Could not save frame: {ref} {name}")
                        frames.append(frame)
                    rows.append({"prediction_index": index, "timestamp_seconds": cut,
                                 "mean_absolute_pixel_difference_minus_0_05_to_plus_0_05":
                                 round(float(np.mean(cv2.absdiff(frames[1], frames[2]))), 2)})
            finally:
                cap.release()
        (target / "frame_index.json").write_text(json.dumps({"source_ref": ref,
            "sample_offsets_seconds": OFFSETS, "events": rows}, indent=2) + "\n")
        results[ref] = len(rows)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--refs", nargs="+", choices=REFS, default=list(REFS))
    args = parser.parse_args(argv)
    print(json.dumps(extract(args.manifest, args.sweep, args.out, refs=args.refs)))


if __name__ == "__main__":
    main()
