"""Deterministic gate for the external retrieval evaluation helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Never, cast


@dataclass(frozen=True, repr=False)
class CoverageCounts:
    """Validated coverage counters for one expected evaluator source file."""

    source_file: str
    statements: int
    covered_statements: int
    branches: int
    covered_branches: int


def _reject_report() -> Never:
    raise ValueError("retrieval evaluator coverage report is invalid")


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _reject_report()
    return cast(dict[str, object], value)


def _counter(values: dict[str, object], name: str) -> int:
    value = values.get(name)
    if type(value) is not int or value < 0:
        _reject_report()
    return value


def validate_coverage_report(
    report: object, expected_files: tuple[str, ...]
) -> tuple[CoverageCounts, ...]:
    """Validate exact source membership and nonnegative exact integer counters."""

    if (
        type(expected_files) is not tuple
        or not expected_files
        or any(type(value) is not str or not value for value in expected_files)
        or len(expected_files) != len(set(expected_files))
    ):
        _reject_report()
    root = _mapping(report)
    files = _mapping(root.get("files"))
    if set(files) != set(expected_files):
        _reject_report()
    results: list[CoverageCounts] = []
    for source_file in expected_files:
        entry = _mapping(files.get(source_file))
        summary = _mapping(entry.get("summary"))
        statements = _counter(summary, "num_statements")
        covered_statements = _counter(summary, "covered_lines")
        branches = _counter(summary, "num_branches")
        covered_branches = _counter(summary, "covered_branches")
        if (
            statements == 0
            or covered_statements > statements
            or covered_statements != statements
            or covered_branches > branches
        ):
            _reject_report()
        results.append(
            CoverageCounts(
                source_file=source_file,
                statements=statements,
                covered_statements=covered_statements,
                branches=branches,
                covered_branches=covered_branches,
            )
        )
    return tuple(results)


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 required")
    root = Path(__file__).resolve().parent.parent
    production = (
        "scripts/retrieval_eval_core.py",
        "scripts/retrieval_eval_metrics.py",
    )
    checked = (*production, "scripts/test_retrieval_eval.py", "scripts/verify_retrieval_eval.py")
    if any(not (root / relative).is_file() for relative in checked):
        raise SystemExit("retrieval evaluator gate is missing a required file")
    with TemporaryDirectory(prefix="memotrace-retrieval-eval-") as temporary:
        coverage_data = str(Path(temporary) / "coverage.data")
        coverage_json = Path(temporary) / "coverage.json"
        commands = (
            ("ruff", "check", "--config", "ml/pyproject.toml", *checked),
            (
                "ruff",
                "format",
                "--check",
                "--config",
                "ml/pyproject.toml",
                *checked,
            ),
            (
                "mypy",
                "--config-file",
                "ml/pyproject.toml",
                "--strict",
                "--explicit-package-bases",
                *checked,
            ),
            (
                "coverage",
                "run",
                "--branch",
                "--source=scripts.retrieval_eval_core,scripts.retrieval_eval_metrics",
                f"--data-file={coverage_data}",
                "-m",
                "pytest",
                "-c",
                "ml/pyproject.toml",
                "scripts/test_retrieval_eval.py",
            ),
            (
                "coverage",
                "report",
                f"--data-file={coverage_data}",
                "--show-missing",
                *production,
            ),
            (
                "coverage",
                "json",
                f"--data-file={coverage_data}",
                "-o",
                str(coverage_json),
            ),
        )
        for command in commands:
            subprocess.run([sys.executable, "-m", *command], cwd=root, check=True)
        try:
            report: object = json.loads(coverage_json.read_bytes())
            counts = validate_coverage_report(report, production)
        except (OSError, UnicodeError, ValueError):
            raise SystemExit("retrieval evaluator coverage report is invalid") from None
        for result in counts:
            print(
                f"{result.source_file} statement gate: "
                f"{result.covered_statements}/{result.statements} = 100%"
            )
            print(
                f"{result.source_file} branch coverage: "
                f"{result.covered_branches}/{result.branches} (reported only)"
            )


if __name__ == "__main__":
    main()
