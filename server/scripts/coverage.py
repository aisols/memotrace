#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Gate pure wire/domain validation separately from IO and orchestration."""
import sys
from pathlib import Path

gates = {"protocol": [0, 0], "retrieval": [0, 0]}
for line in Path(sys.argv[1]).read_text().splitlines()[1:]:
    block, statements, hits = line.split()
    for package, counters in gates.items():
        if block.startswith(f"memotrace/server/internal/{package}/"):
            counters[1] += int(statements)
            counters[0] += int(statements) if int(hits) else 0
failed = []
for package, (covered, total) in gates.items():
    if not total:
        failed.append(f"pure {package}/domain coverage missing")
        continue
    percent = 100 * covered / total
    print(f"pure {package}/domain statement coverage: {percent:.1f}% ({covered}/{total}); required >=85%")
    if 100 * covered < 85 * total:
        failed.append(f"pure {package}/domain coverage gate failed")
if failed:
    raise SystemExit("; ".join(failed))
