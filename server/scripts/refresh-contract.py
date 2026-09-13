#!/usr/bin/env python3
"""Explicit maintenance operation, never part of ordinary builds/tests.

SPDX-License-Identifier: AGPL-3.0-only
Copy canonical contract bytes with deterministic, reviewable provenance/hashes.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--source-base", required=True)
parser.add_argument(
    "--provenance",
    choices=["unreleased-working-tree", "unreleased-revision", "released-revision"],
    required=True,
)
parser.add_argument("--check", action="store_true", help="compare explicit canonical source and provenance without changing the snapshot")
args = parser.parse_args()
if not re.fullmatch(r"[0-9a-f]{40}", args.source_base):
    raise SystemExit("full lower-case 40-hex source base revision required")
files = ["schemas/ingestion.schema.json", "openapi/ingestion.json", "schemas/retrieval.schema.json", "openapi/retrieval.json", "VERSION"]
contents = {name: (args.source / name).read_bytes() for name in files}
version = "0.2.0"
wire_versions = {"ingestion": "0.1.0", "retrieval": "0.2.0"}
for family, wire_version in wire_versions.items():
    schema = json.loads(contents[f"schemas/{family}.schema.json"])
    api = json.loads(contents[f"openapi/{family}.json"])
    if schema["$defs"]["ContractVersion"]["const"] != wire_version or api["info"]["version"] != wire_version:
        raise SystemExit(f"{family} wire version mismatch")
if contents["VERSION"] != (version + "\n").encode("ascii"):
    raise SystemExit("bundle version mismatch")
destination = Path(__file__).resolve().parents[1] / "internal/contract/snapshot"
manifest = {
    "contract_version": version,
    "wire_versions": wire_versions,
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
