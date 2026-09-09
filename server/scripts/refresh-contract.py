#!/usr/bin/env python3
"""Explicit maintenance operation, never part of ordinary builds/tests.

SPDX-License-Identifier: AGPL-3.0-only
Copy canonical contract bytes with deterministic, reviewable provenance/hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--source-base", required=True)
parser.add_argument("--provenance", choices=["unreleased-working-tree", "released-revision"], required=True)
parser.add_argument("--check", action="store_true", help="compare explicit canonical source and provenance without changing the snapshot")
args = parser.parse_args()
files = ["schemas/ingestion.schema.json", "openapi/ingestion.json", "VERSION"]
contents = {name: (args.source / name).read_bytes() for name in files}
schema = json.loads(contents[files[0]])
api = json.loads(contents[files[1]])
version = schema["$defs"]["ContractVersion"]["const"]
if api["info"]["version"] != version or contents["VERSION"] != (version + "\n").encode("ascii"):
    raise SystemExit("contract version mismatch")
destination = Path(__file__).resolve().parents[1] / "internal/contract/snapshot"
manifest = {
    "contract_version": version,
    "source_component": "contracts",
    "source_base_revision": args.source_base,
    "provenance": args.provenance,
    "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
}
manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
for name, data in {**contents, "manifest.json": manifest_bytes}.items():
    path = destination / name
    if args.check:
        if path.read_bytes() != data:
            raise SystemExit(f"canonical snapshot differs: {name}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
print(json.dumps(manifest, indent=2))
