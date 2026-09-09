"""Component quality entry point: uv run --locked python -m tools.verify.

SPDX-License-Identifier: AGPL-3.0-only
"""

import sys
import unittest

from tools.contract import ROOT


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful() or result.skipped or result.testsRun == 0:
        return 1
    print("PASS: canonical JSON Schema, OpenAPI 3.1, offline refs, fixtures, boundary matrices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
