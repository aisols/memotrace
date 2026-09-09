# Independent ingestion verification — 2026-09-09

## Scope and provenance

This records actual tool results supplied by the coordinating main agent after
the final RFC 6750 ASCII-space fix; the documentation builder did not rerun tests.
Branch: `feat/server-ingestion`, based on `f4e53f8`. The implementation is
**uncommitted and unreleased**. The base identifies provenance, not an exact commit
containing the tested working-tree changes. No source release, PR or hosted check
run is claimed.

## Independent review

- Server/security reviewer: **PASS**.
- Contract/conformance and assembly reviewer: **PASS**; four CI action pins verified.
- All eight findings were resolved, covering Unicode/NUL handling, exact decimals,
  origins/TTL, auth challenges and scheme/spacing conformance. Earlier failing
  regression probes are resolved findings, not current blockers.
- The **85% pure protocol/domain coverage gate** was independently approved together
  with the required behavioral tests; no whole-application percentage was imposed.

## Server verification

From `server/`, main ran **`bash scripts/verify.sh` — PASS**, using Go 1.26.4.
This checked formatting, module verification, vet, binary build and embedded snapshot
hashes, then race-enabled tests with required PostgreSQL 15 in an isolated container.
Coverage included real TLS pairing/upload/read/revocation/graceful shutdown through
native-host Go CLI subprocesses, two-owner isolation, concurrency, actual deferred
SQL COMMIT failure, process-crash recovery and simulated ENOSPC/fsync failures.

Pure protocol/domain coverage: **95.2% (238/250 statements)**, above the 85% gate.
Other package reports: CLI 68.7%, archive 83.9%, bootstrap 85.5%, contract 68.5%,
HTTP 86.2%. These are descriptive, not additional percentage gates. PostgreSQL's
package-local 0% report does not include its execution from HTTP integration tests.
Main's post-verification Docker container listing filtered for MemoTrace was empty;
all disposable test containers were removed.

## Contract and isolation verification

From `contracts/`, `uv run --locked --offline python -m tools.verify` with an isolated
`UV_CACHE_DIR`: **PASS, 977 tests**, Python 3.12.3 and uv 0.11.3.
Standalone contract verification also **passed 977 tests** in a read-only `/work`
containing only the contracts component and its provisioned locked-venv site packages.
It used `--network none`, temporary `/tmp`, and
`PYTHONPATH=/work/.venv/lib/python3.12/site-packages`, with no enclosing repository
or sibling mounts. This proves isolated execution, not a fresh offline installation.
Python container: `python@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe`.

From the repository root, main's snapshot parity check **passed**, including VERSION:

```sh
python3 server/scripts/refresh-contract.py --check --source contracts \
  --source-base f4e53f8 --provenance unreleased-working-tree
```

The consumer manifest records contract **0.1.0** and unreleased working-tree provenance.
Canonical SHA-256 values verified by main:

- Schema: `9dcc7ab98a2d77357c3a00e966590e282525962fa33c2aeb58c1b12ccdecb783`
- OpenAPI: `eafc37a24fddd70c6afd6c6ed1290f60ad62c691f650ba8af365cfbd9156b37b`

The manifest additionally records the checked VERSION hash; ordinary server builds
consume only this local snapshot.

## Assembly and container checks

- `actionlint .github/workflows/ingestion.yml`: **PASS**, actionlint 1.7.7.
- `bash -n server/scripts/verify.sh` and `git diff --check`: **PASS**.
- From `server/`, `docker build -t memotrace-server:ingestion-dev .`: **PASS**,
  using only the server component as context, without parent sources.
- `docker run --rm --network none --read-only memotrace-server:ingestion-dev serve --help`:
  **PASS**, non-root UID/GID **10001:10001**.
- Built image ID: `sha256:f5e276d98422b2e099748ea5fec8c3e20ba372ced2640bc8dfab13b1c26fc196`.

The container smoke exercised CLI help only. It does not establish deployed-container
TLS/PostgreSQL operation; the full TLS lifecycle evidence came from native-host CLI tests.

## Remaining gates and limits

Hosted CI has not run because no push/PR was requested. Authorized delivery must still
satisfy PR/CI and latest-revision merge gates. This is historical evidence; subsequent
source changes require applicable verification and review again.
No device/Android synchronization, physical power-loss, backup restoration, throughput,
multiuser production, E2EE or encryption-attestation evidence is claimed. Tests used
synthetic data/certificates, not real photos or private keys from a deployment.
