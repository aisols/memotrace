"""Print a safe aggregate from an external benchmark report, without source attribution."""

import argparse
import json
from pathlib import Path

from memotrace_ml.common import JSON, file_digest, object_value, read_json

PRIMARY_MACRO_VERSIONS = frozenset(
    {"openimages-retrieval-pilot-v2", "openimages-retrieval-pilot-v3"}
)


def macro_eligibility(version: JSON) -> str:
    return (
        "both-polarities-primary"
        if version in PRIMARY_MACRO_VERSIONS
        else "historical-positive-only-diagnostic"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = read_json(args.report)
    safe: dict[str, JSON] = {
        key: report[key]
        for key in (
            "dataset",
            "manifest_sha256",
            "ground_truth_sha256",
            "selection_sha256",
            "model",
            "source_counts",
            "runtime",
            "model_load_seconds",
            "modes",
            "macro_averages",
            "secondary_positive_only_macro_averages",
            "language_evaluation",
            "source_asset_count",
            "unique_content_count",
            "content_alias_count",
            "acquisition_sha256",
            "duration_seconds",
        )
        if key in report
    }
    safe["version"] = report["version"]
    safe["macro_eligibility"] = macro_eligibility(report["version"])
    safe["implementation_sha256"] = object_value(report["model_identity"]).get(
        "implementation_sha256"
    )
    safe["report_sha256"] = file_digest(args.report)
    print(json.dumps(safe, indent=2, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
