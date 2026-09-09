#!/usr/bin/env python3
"""Run the real quality command in fresh isolated copies; mutate only copied tests."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    parent = args.temp_parent.resolve(strict=True)
    if parent == source or source in parent.parents:
        parser.error("temporary copies must be outside the Android component")
    evidence = Path(tempfile.mkdtemp(prefix="memotrace-quality-", dir=parent))
    tasks = [
        "--no-daemon", "clean", ":capture-core:check", ":app:testDebugUnitTest",
        ":app:lintDebug", "spotlessCheck", ":app:assembleDebug",
        ":app:assembleDebugAndroidTest",
    ]
    cases = [("positive", None, None)]
    cases += [(f"{component}-{mode}", component, mode)
              for component in ("capture-core", "app")
              for mode in ("absent", "all-ignored", "single-ignored")]
    print(f"Evidence: {evidence}", flush=True)
    for name, component, mode in cases:
        copy = evidence / name
        shutil.copytree(source, copy, ignore=shutil.ignore_patterns(
            "build", ".gradle", ".kotlin", ".android", "local.properties",
        ))
        if component:
            tests = copy / component / "src" / "test"
            if mode == "absent":
                shutil.rmtree(tests)
            else:
                changed = 0
                for file in sorted(tests.rglob("*.kt")):
                    text, count = re.subn(
                        r"(?m)^([ \t]*)@Test\b",
                        r"\1@org.junit.Ignore\n\1@Test",
                        file.read_text(), count=1 if mode == "single-ignored" else 0,
                    )
                    if count:
                        file.write_text(text)
                        changed += count
                        if mode == "single-ignored":
                            break
                if not changed:
                    raise RuntimeError(f"{name}: no test annotations were mutated")
        log = evidence / f"{name}.log"
        with log.open("w") as output:
            result = subprocess.run([str(copy / "gradlew"), *tasks], cwd=copy,
                                    stdout=output, stderr=subprocess.STDOUT, check=False)
        text = log.read_text()
        if component:
            reasons = ("no test class files", "missing XML results", "zero tests") if mode == "absent" else ("skipped tests",)
            expected = any(f"Test results gate: :{component}:" in line
                           and any(reason in line for reason in reasons)
                           for line in text.splitlines())
            if result.returncode == 0 or not expected:
                raise RuntimeError(f"{name}: expected test-results gate rejection, inspect {log}")
            print(f"PASS {name}: exit {result.returncode}, expected gate rejection", flush=True)
        else:
            if result.returncode != 0:
                raise RuntimeError(f"isolated positive command failed: {log}")
            print("PASS isolated positive: exit 0", flush=True)
    print("PASS: positive plus six negative cases; source tests unchanged", flush=True)


if __name__ == "__main__":
    main()
