#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Gate pure wire/domain validation separately from IO and orchestration."""
import sys
from pathlib import Path

covered = total = 0
for line in Path(sys.argv[1]).read_text().splitlines()[1:]:
    block, statements, hits = line.split()
    if block.startswith("memotrace/server/internal/protocol/"):
        total += int(statements)
        covered += int(statements) if int(hits) else 0
if not total:
    raise SystemExit("pure/domain coverage missing")
percent = 100 * covered / total
print(f"pure protocol/domain statement coverage: {percent:.1f}% ({covered}/{total}); required >=85%")
if percent < 85:
    raise SystemExit("pure protocol/domain coverage gate failed")
