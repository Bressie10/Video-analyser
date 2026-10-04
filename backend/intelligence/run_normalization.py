"""Run offline research comparisons: python -m intelligence.run_normalization fixtures.json."""

import argparse
import json
from pathlib import Path

from intelligence.normalization import evaluate, evaluate_baseline
from intelligence.schemas.benchmark import BenchmarkVideo


def run(payload: dict) -> list[dict]:
    videos = [BenchmarkVideo.model_validate_json(json.dumps(row)) for row in payload["videos"]]
    by_ref = {video.source.reference: video for video in videos}
    if len(by_ref) != len(videos):
        raise ValueError("Video references must be unique; use repeated source IDs for duplicate checks")
    output = []
    for request in payload["requests"]:
        target = by_ref[request["target"]]
        if request.get("comparison", "peer_videos") == "peer_videos":
            output.extend(evaluate(videos, target, request["metric"]))
        elif request["comparison"] == "account_baseline":
            output.extend(evaluate_baseline(target, request["metric"],
                                            request.get("baseline_context")))
        else:
            raise ValueError("Unknown normalization comparison")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Local JSON with videos and requests")
    args = parser.parse_args()
    print(json.dumps(run(json.loads(args.fixture.read_text())), indent=2))


if __name__ == "__main__":
    main()
