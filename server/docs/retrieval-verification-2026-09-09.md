# Retrieval Go builder verification — 2026-09-09

> **HISTORICAL PRE-HARDENING BUILDER RECORD.** This records the initial pre-review
> run. Its model/generation IDs and coverage percentages apply only to that source.
> See [review-fix verification](retrieval-review-verification-2026-09-09.md) for a
> later recorded Go follow-up, full source-base provenance and the independently
> approved retrieval gate. Neither report supplies current live model identities:
> fingerprints and generations are unavailable pending fresh v3 acquisition and a
> live hardened-source model/data run.

Uncommitted/unreleased working tree on `feat/object-search-history`, based on
`0ebc2a8`. This is builder evidence; independent main/review/CI/merge gates remain.
The Go builder edited `server/` outside the parallel builders' `ml/` and
`benchmarks/` ownership. Canonical retrieval documents were consumed through the
explicit maintenance generator, with no ordinary sibling-source imports.

## Executed checks

- `bash scripts/verify.sh`: passed with own uniquely labelled disposable PG15,
  non-superuser migration owner and nonowner runtime role, module checks, gofmt,
  vet, CLI build, embedded schema hashes, race-enabled serialized-package DB tests.
- The same full verifier passed from an isolated component copy at
  `/tmp/opencode/memotrace-go-extraction-l7Ik0O`, without sibling components or an
  installed ML virtual environment. The optional external-model evidence test is
  explicitly separate and skips unless its evidence directory is supplied.
- `docker build -t memotrace-server:local .`: passed independently of Python/models;
  Go-only image config ID
  `sha256:cb194e77020cf94252b94d94add5f524d5e915b1ef0242b9c414e573cc3c9e88`.
- Read-only `scripts/refresh-contract.py --check` passed against the explicit
  canonical source, base `0ebc2a8`, unreleased-working-tree provenance. Both legacy
  document SHA-256 values remain unchanged; both new documents and VERSION are pinned.
- `TestExternalGenuineRetrievalEvidence` passed on all seven saved real CLI/TLS
  responses using the genuine embedded JSON Schema2020-12 validator.
- Existing pure protocol gate: **94.4%, 238/252 statements**, required >=85%.
  Package-local retrieval domain coverage: **87.3%** (reported, no new arbitrary
  whole-app percentage introduced). Inference IPC tests: **78.3%**. New HTTP
  coverage: **88.5%**; CLI **69.8%**; postgres **43.9%**. PostgreSQL/search/archive
  also have integration coverage from other packages that package-local figures
  do not attribute back to the implementation package.
- The then-new tests cover v1 committed metadata/receipt/JPEG preservation, sessionless
  elapsed time remaining unsequenced, repeat migration, default-deny/cross-owner RLS
  on all new tables, no duplicate leases/results, expiry/replacement fencing,
  persistent malformed-result attempts/exhaustion, and actual deferred SQL COMMIT
  failure rolling back both vectors and completion.
  Frame assets use independent server-generated UUIDs: a client-selected frame ID
  equal to a dataset asset ID cannot hide the new committed frame. A regression
  exercises that collision through actual ingestion and asset-original routes.
- Actual HTTP/schema tests cover decimal boxes/scores, source and identical-byte
  aliases, deterministic asset deduplication, exclusive cutoff before rank/group,
  complete first/last/group bounds before evidence limit, same-sequence selection,
  unknown-time null history, partial indexing truncation, cross-owner query/original
  denial, revoked-during-inference denial, and 5000-asset/50000-vector scope gates.
- CLI subprocess test uses a **test-binary-only** fake JSONL worker and exercises
  dataset-import/index/search/history plus TLS serving/pairing/search/history.
  IPC subprocess tests verify secret-free environment, stderr/input/output limits,
  malformed/wrong-ID/wrong-model/wrong-norm output, child death/cancellation and restart.
  These synthetic tests are correctness evidence, not model-quality measurements.

## Genuine model + 48 Open Images assets

Executed `python3 scripts/retrieval-smoke.py` using the pre-acquired model and
manifest paths documented in [retrieval setup](retrieval.md). It used its **own**
throwaway PostgreSQL database, real Go CLI/server, and real offline Python JSONL
worker. No model/data download or retrieval-quality benchmark was duplicated.

Artifacts were written outside Git:
`/tmp/opencode/memotrace-go-search-smoke/go-smoke-14d08ca2964fe8279c494ef4/`.
The runner removed its own PostgreSQL container after completion. Generated TLS
keys and JPEG copies were written under that private external run directory.

| Mode | Assets completed | Failed attempts | Persisted regions | Pending / failed |
| --- | ---: | ---: | ---: | --- |
| Full | 48 | 0 | 48 | 0 / 0 |
| Full + overlap | 48 | 0 | 322 | 0 / 0 |

Full generation:
`7078cd96b4046a1969d1799e685246c0eb1fdc553d4d272848fdaa0dbe836c4a`.
Overlap generation:
`6e3e1c569a6c1e5463e1be1ed63e6d1487561fd1a6927a6f3ec8dceed0df386a`.
Both agree with the independent Python builder's model/policy fingerprints; Go
obtained the actual dimension from `describe`.

English/Russian CLI queries passed in both modes. TLS trusted invitation/pairing,
HTTP search/history and hash-verified exact original retrieval passed. Health and
pairing emitted ingestion wire0.1.0; retrieval emitted0.2.0. Image-source assets and
identical-byte aliases were excluded. Open Images emitted `history_available:false`,
empty temporal observations and null first/last bounds. The runner intentionally
records no recall/latency quality metrics; the [Python pilot](../benchmarks/openimages-pilot-2026-09-09.md)
owns those separate measured definitions and limitations.

## Limitations and remaining independent gates

Exact small-corpus baseline only (5000 assets/50000 regions), no pgvector/ANN, online
index scheduler, same-instance identity, tracking, or acquisition inference. Offline
operator commands require service stopped/root lock. ML dependencies/models are
optional and absent from the Go-only Docker image. Child env is sanitized and model
loading is offline; same-UID filesystem access is not an OS sandbox. No private data,
Ego4D, device, physical power-loss, encrypted deployment, restored-backup, large-corpus
throughput or production shared-service evidence is claimed. At the time, independent
verification of a later revision, review completion and authorized delivery remained
assigned to Main; this record does not claim completion of those later gates.
