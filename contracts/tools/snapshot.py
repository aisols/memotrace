"""Read-only controlled-bundle provenance; never writes a consumer snapshot.

SPDX-License-Identifier: AGPL-3.0-only
"""

import argparse
from hashlib import sha256
import json
import re

from tools.contract import BUNDLE_VERSION, Contract, FAMILIES, ROOT


def manifest(source_repository, source_revision, source_status, root=ROOT):
    """Hash the complete wire bundle after validating its family identities.

    A working-tree revision identifies its base, not a commit containing new files.
    Consumer-owned refresh tools may translate these fields, but must preserve
    their meaning and verify byte parity. No Git or network operations occur here.
    """
    if not source_repository or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("Repository identity and full lower-case source revision required")
    if source_status not in {"committed", "unreleased-working-tree"}:
        raise ValueError("Explicit source status required")
    contract = Contract(root)
    contract.validate_documents()
    paths = ["VERSION", *[family[key] for family in FAMILIES.values() for key in ("schema", "openapi")]]
    return {
        "bundle_version": BUNDLE_VERSION,
        "wire_versions": {name: family["version"] for name, family in FAMILIES.items()},
        "source_repository": source_repository,
        "source_revision": source_revision,
        "source_status": source_status,
        "files": {path: sha256((contract.root / path).read_bytes()).hexdigest() for path in paths},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-status", required=True, choices=("committed", "unreleased-working-tree"))
    args = parser.parse_args()
    print(json.dumps(manifest(args.source_repository, args.source_revision, args.source_status), indent=2))


if __name__ == "__main__":
    main()
