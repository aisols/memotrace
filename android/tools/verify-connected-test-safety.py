#!/usr/bin/env python3
"""Exercise APK-retention gates in an isolated component copy; never run a device task."""

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
        parser.error("temporary verification must be outside the Android component")
    evidence = Path(tempfile.mkdtemp(prefix="memotrace-connected-safety-", dir=parent))
    copy = evidence / "android"
    shutil.copytree(source, copy, ignore=shutil.ignore_patterns(
        "build", ".gradle", ".kotlin", ".android", "local.properties",
    ))
    properties = copy / "gradle.properties"
    original = properties.read_text()
    build_script = copy / "app" / "build.gradle.kts"
    original_build = build_script.read_text()
    retention = "android.injected.androidTest.leaveApksInstalledAfterRun"
    incompatible = "android.experimental.testOptions.uninstallIncompatibleApks"
    gate = ":app:verifyConnectedTestSafety"
    wiring = ":app:verifyConnectedTestSafetyWiring"
    cases = [
        ("defaults", [gate, wiring], None, True),
        ("release-defaults", [gate, wiring], None, True),
        ("retention-false", [gate, f"-P{retention}=false"], None, False),
        ("incompatible-true", [gate, f"-P{incompatible}=true"], None, False),
        ("retention-missing", [gate], retention, False),
        ("incompatible-missing", [gate], incompatible, False),
        ("retention-empty", [gate, f"-P{retention}="], None, False),
        # Wiring executes only the named first guard on the actual AGP tasks, not their device actions.
        ("inline-retention-false", [wiring, f"-P{retention}=false"], None, False),
        ("inline-incompatible-true", [wiring, f"-P{incompatible}=true"], None, False),
    ]
    print(f"Evidence: {evidence}", flush=True)
    for name, tasks, missing, positive in cases:
        build_script.write_text(original_build.replace("android {", 'android {\n    testBuildType = "release"', 1)
                                if name == "release-defaults" else original_build)
        text = original
        if missing:
            text, removed = re.subn(rf"(?m)^{re.escape(missing)}=.*\n?", "", text)
            if removed != 1:
                raise RuntimeError(f"{name}: expected one explicit component property")
        properties.write_text(text)
        log = evidence / f"{name}.log"
        with log.open("w") as output:
            result = subprocess.run([str(copy / "gradlew"), "--no-daemon", *tasks], cwd=copy,
                                    stdout=output, stderr=subprocess.STDOUT, check=False)
        text = log.read_text()
        if positive:
            variant = "Release" if name == "release-defaults" else "Debug"
            marker = f"Verified guard before DeviceProvider action: :app:connected{variant}AndroidTest"
            if result.returncode != 0 or marker not in text:
                raise RuntimeError(f"{name}: positive/wiring check failed, inspect {log}")
        else:
            expected = (f"Cannot parse project property {retention}=''" if name == "retention-empty"
                        else "Connected test safety gate:")
            if result.returncode == 0 or expected not in text:
                raise RuntimeError(f"{name}: expected safety rejection, inspect {log}")
        print(f"PASS {name}: exit {result.returncode}; no device action invoked", flush=True)
    print("PASS: debug/release wiring positives plus seven safety negatives; original component untouched", flush=True)


if __name__ == "__main__":
    main()
