"""Run: python -m intelligence.evaluation {validate,summary,agreement} DATASET_DIR."""

import argparse
import json

from .agreement import compare_all
from .dataset import load_dataset, summarize


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "summary", "agreement"))
    parser.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        dataset, _ = load_dataset(args.directory)
        if args.command == "validate":
            result = {"valid": True, "annotations": len(dataset.annotations),
                      "sources": len({a.source.reference_id for a in dataset.annotations})}
        elif args.command == "summary":
            result = summarize(dataset)
        else:
            result = compare_all(dataset.annotations)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Invalid dataset: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
