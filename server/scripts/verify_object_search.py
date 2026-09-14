"""Separate model/data-free gate for the object-search experiment and its pure core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

CORE = "scripts/object_search_core.py"
CHECKED = (
    CORE,
    "scripts/test_object_search_core.py",
    "scripts/object_search_vision.py",
    "scripts/test_object_search_vision.py",
    "scripts/object_search_experiment.py",
    "scripts/test_object_search_experiment.py",
    "scripts/verify_object_search.py",
)


def coverage_counts(report: object) -> tuple[int, int, int, int]:
    """Require this exact file's >=95% statements; branches never offset missing lines."""
    if not isinstance(report, dict) or not isinstance(report.get("files"), dict):
        raise ValueError("invalid object-search coverage report")
    files = report["files"]
    if set(files) != {CORE} or not isinstance(files[CORE], dict):
        raise ValueError("coverage must contain exactly the pure core")
    summary = files[CORE].get("summary")
    if not isinstance(summary, dict):
        raise ValueError("missing core coverage summary")
    counters = tuple(
        summary.get(name)
        for name in ("num_statements", "covered_lines", "num_branches", "covered_branches")
    )
    if any(type(value) is not int or value < 0 for value in counters):
        raise ValueError("invalid coverage counters")
    statements, covered, branches, covered_branches = cast(tuple[int, int, int, int], counters)
    if (
        not statements
        or covered > statements
        or covered_branches > branches
        or covered * 100 < statements * 95
    ):
        raise ValueError("pure core per-file 95% statement gate failed")
    return statements, covered, branches, covered_branches


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 required")
    root = Path(__file__).absolute().parent.parent
    if any(not (root / path).is_file() for path in CHECKED):
        raise SystemExit("object-search gate is missing a required file")
    environment = {
        **os.environ,
        "MYPYPATH": str(root / "ml"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    with TemporaryDirectory(prefix="memotrace-object-search-") as temporary:
        data = str(Path(temporary) / "coverage.data")
        report_path = Path(temporary) / "coverage.json"
        environment["MYPY_CACHE_DIR"] = str(Path(temporary) / "mypy")
        environment["RUFF_CACHE_DIR"] = str(Path(temporary) / "ruff")
        tests = tuple(path for path in CHECKED if Path(path).name.startswith("test_"))
        commands = (
            ("ruff", "check", "--config", "ml/pyproject.toml", *CHECKED),
            ("ruff", "format", "--check", "--config", "ml/pyproject.toml", *CHECKED),
            (
                "mypy",
                "--config-file",
                "ml/pyproject.toml",
                "--strict",
                "--explicit-package-bases",
                *CHECKED,
            ),
            (
                "coverage",
                "run",
                "--branch",
                "--source=scripts.object_search_core",
                f"--data-file={data}",
                "-m",
                "pytest",
                "-c",
                "ml/pyproject.toml",
                *tests,
            ),
            ("coverage", "report", f"--data-file={data}", "--show-missing", CORE),
            ("coverage", "json", f"--data-file={data}", "-o", str(report_path)),
        )
        for command in commands:
            subprocess.run([sys.executable, "-m", *command], cwd=root, env=environment, check=True)
        statements, covered, branches, covered_branches = coverage_counts(
            json.loads(report_path.read_bytes())
        )
        print(f"{CORE} statement gate: {covered}/{statements} = {covered / statements:.2%} >=95%")
        print(f"{CORE} branches: {covered_branches}/{branches} (reported separately; no threshold)")


if __name__ == "__main__":
    main()
