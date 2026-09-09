# Initial Ingestion Contract: Design and Status

Status: **Implemented `0.1.0` development contract, unreleased**, 2026-09-09.
The canonical JSON Schema, OpenAPI JSON, synthetic fixtures, and standalone
executable checks now exist. They define requirements; they are not evidence
of server conformance, deployment security, physical power-loss behavior, or
Android synchronization. Independent contract review and consumer verification
remain delivery gates. SPEC remains the original product baseline.

## Implemented contract surface

- [Canonical schema](../schemas/ingestion.schema.json): named `$defs` for `Health`,
  `Invitation`, `PairRequest`, `PairResponse`, `FrameMetadata`, `ManifestRequest`,
  `ManifestResponse`, `Receipt`, `Error`, and reusable constraints.
- [OpenAPI 3.1](../openapi/ingestion.json): process health, one-time invitation
  redemption, transactional metadata registration, full-file original upload,
  receipt recovery, and authorized exact-byte original retrieval.
- [Normative protocol](protocol.md): identities, trust, time meanings, optional
  legacy metadata normalization, byte integrity and historical receipt promises,
  transactional/retry semantics, resource limits, and explicit HTTP errors.
- [Fixtures](../examples/README.md), [quality command/gates](quality.md), and
  [snapshot/release/compatibility procedure](releases.md).

`contracts/` owns public formats. SQL, migrations, jobs, file layout, runtime
authorization, and inference remain server-owned; mobile UI/local persistence
remain Android-owned. Consumers use integrity-pinned snapshots or release
artifacts, with no ordinary build dependence on sibling source trees.

## Selected first-slice decisions

| Topic | Selected contract requirement |
| --- | --- |
| Bootstrap | Trusted out-of-band invitation payload with HTTPS origin and SHA-256 of the DER leaf certificate; certificate/name/validity verified before redemption |
| Device identity | One-time invitation issues a random 32-byte bearer token scoped to one archive; owner identity is server-derived |
| Ingestion | Register immutable expected metadata first, in batches of 1..100, then PUT full original JPEGs |
| Evidence identity | Frame UUID within authorized archive; identical bytes under different IDs are separate evidence, with no physical deduplication |
| Integrity | Exact SHA-256/byte length, JPEG SOI/EOI and header/dimension limits, followed by durable file plus metadata/job commit |
| Receipt | Stable historical `archive_committed` result, recoverable after a lost ACK; original retrieval separately verifies current bytes |
| Retry | Missing/null optional metadata normalizes to unknown; matching registration and full-file repeats are safe; immutable differences conflict |
| Time | Request wall time is not shutter time; elapsed time only meaningful in documented session/boot scope; saved time may describe recovery |
| Transport | HTTPS deployment, TLS >=1.2, bounded bodies; no byte-range resume in this slice |
| Storage trust | Trusted local operator and operator-managed encrypted volumes/backups; no E2EE or encryption attestation claim |

The protocol document is normative when a high-level design phrase is less
specific. Machine-readable validation and the written semantic requirements
jointly define conformance; accepting a JSON instance is only one part.

## Remaining work and evidence boundaries

Consumers must test actual pairing expiry/replay and revocation, owner isolation,
batch atomicity, lost ACK/restart recovery, immutable conflicts, concurrent
uploads, integrity refusal, and storage/SQL/publication fault handling. Their
tests must use actual request/response bytes against a controlled contract
snapshot, not merely duplicate language-specific structs.

Android legacy field mapping requires its reviewed recorder revision. A null
session cannot establish a timeline across recordings. Requested camera settings
cannot prove achieved dimensions; public Gallery URIs are device locators and
their contents may change externally. Clients must freeze or reverify their
upload source. No missing metadata should be fabricated to fill this contract.

No ML/OCR completion, indexing/search/evidence endpoints, speech, deletion,
retention-driven phone eviction, cloud VLM, Redis, or E2EE formats are specified.
A future deletion feature needs tombstones and offline queue/restore semantics;
a future phone-eviction feature needs an explicit retention/backup decision.
Archive commitment is distinct from visual quality, indexing, backup, or
permanent availability. Keep these future features out of the wire surface
until their first implementation requires a reviewed contract change.
