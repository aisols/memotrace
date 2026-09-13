"""Component-local checks; no model or public data required."""

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 required")
    root = Path(__file__).resolve().parent.parent
    commands = [
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["mypy", "--config-file", "pyproject.toml", "memotrace_ml", "tests"],
        ["coverage", "run", "-m", "pytest", "tests"],
        ["coverage", "report"],
        ["coverage", "json"],
    ]
    for command in commands:
        subprocess.run([sys.executable, "-m", *command], cwd=root, check=True)
    report = json.loads((root / ".coverage-images.json").read_bytes())
    totals = report["totals"]
    statements = totals["num_statements"]
    covered = totals["covered_lines"]
    # Independent review approved >=95% *statement* coverage of spatial logic.
    # coverage.py's combined line+branch percentage is reported, not this gate.
    if not statements or covered / statements < 0.95:
        raise SystemExit("memotrace_ml.images statement coverage must be >=95%")
    print(f"images statement gate: {covered}/{statements} = {covered / statements:.2%} >=95%")


if __name__ == "__main__":
    main()
