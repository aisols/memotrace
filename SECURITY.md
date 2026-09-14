# Security Policy

## Current Status

MemoTrace has no released or supported software versions yet. The repository
contains an early local-only Android recorder and an executable, unreleased
Go ingestion server with bounded experimental image/text retrieval and candidate
history. Contract bundle 0.2.0 preserves ingestion wire 0.1.0 and adds retrieval
wire 0.2.0. It is not a production-ready system.
The recorder requests no network permission and disables backup; it does not yet
synchronize its archive. The broader design includes controls not implemented by
this slice. Subsequent implementation changes require applicable independent review
and final-revision verification.

## Ingestion Slice: Implemented Boundary and Limits

The [server](server/README.md) serves HTTPS only (TLS >=1.2), binding to loopback
by default; LAN exposure requires an explicit bind. Local administrative commands
provide migrations, archive creation, invitations and device revocation. There is
no public administrative API or implemented QR/Android pairing UI. Invitation JSON
is transported manually through a trusted out-of-band channel. Invitations are
single-use with a default/maximum lifetime of 10 minutes; trusted bootstrap checks
the leaf certificate's SHA-256 pin, hostname, validity and live TLS verification.
Certificate rotation requires trusted re-bootstrap.

Archive-scoped bearer tokens authenticate ingestion/read requests. Only credential
hashes are stored; raw invitation/device tokens appear in direct CLI output or the
pairing response and must be protected. A lost successful pairing response requires
local revocation and re-enrollment. Revocation rejects newly authorized requests
and is rechecked before upload commit; an already-authorized download may finish.

PostgreSQL 15 uses separate local migration/admin and nonowner runtime roles, with
transaction-local owner context and default-deny RLS for content tables. Runtime
startup rejects unsafe privileges. These controls constrain application mistakes;
they do not provide secrecy from the trusted root/database operator or an attacker
holding runtime database credentials. See the precise
[SQL and storage boundary](server/docs/storage.md).

At-rest protection requires **operator-provisioned encrypted volumes and backups**.
The application does not provision or attest encryption, implement E2EE, or protect
plaintext processing from a privileged administrator. Protect and back up encryption
recovery keys and certificate keys separately; credential reset cannot recover lost
encryption keys. Coherent PostgreSQL/original backups and clean-node restoration
must be arranged and verified by the operator. Automated backup/repair is absent.

Receipts record historical durable commitment under the documented Linux filesystem
and PostgreSQL settings. They do not establish current byte availability, backup,
ML completion or phone-eviction permission. Original reads verify current bytes and
return a generic integrity error for missing/corrupt committed content; historical
receipts can remain available. `/healthz` is process liveness, not archive health.
Public errors must not expose payloads, tokens, SQL or filesystem paths; retryability
and integrity-recovery handling are defined in the
[protocol](contracts/docs/protocol.md#error-mapping-and-retry).

Synthetic two-owner, TLS, database and process/fault tests are component gates,
not proof of physical power-loss durability, restored-backup recovery or production
shared-service readiness. Cloud analysis and Android synchronization remain
unimplemented. The [ingestion decision](docs/decisions/0006-ingestion-v0-1.md)
records that historical slice; the [retrieval decision](docs/decisions/0007-object-retrieval.md)
extends implementation direction without claiming security certification.

## Experimental Retrieval and Public Data

The [retrieval slice](server/docs/retrieval.md) adds archive-scoped assets, indexing
leases, exact-cosine image/text search and candidate history. It rejects corpora
above 5000 archive assets or 50000 regions in a generation before query filtering;
these are bounded experiment limits, not a large-archive availability guarantee.
HTTP uses existing archive credentials; local import/index/search/history are
trusted operator commands. Ingestion receipts remain independent of indexing.

The optional [Python worker](server/ml/README.md) uses pre-acquired, hash-verified
SigLIP2 files, offline loading and no remote model code or runtime download. Go owns
jobs, persistence and bounded subprocess lifecycle; the child receives no inherited
DB/admin/AWS/device credentials. It is a trusted same-UID subprocess, **not an OS
filesystem/network sandbox**. The standalone Docker image is Go-only; a combined
Python/model deployment is not provided.

User-directed **public Open Images and synthetic experiments** explicitly defer
encrypted deployment. Keep their downloaded artifacts, annotations, attribution,
model files and raw reports outside Git. This deferral does not approve unencrypted
private recordings, crops, embeddings, queries or history; private deployment still
requires the operator-provisioned encryption, key custody and recovery above.
Public-data provenance and [model/dataset licensing](docs/licensing.md#third-party-material)
remain applicable.

Cosine scores and crop matches are candidates, not calibrated confidence, learned
stable physical-object identity or tracking. History uses only explicit source
clocks; Open Images has none and cannot establish chronology or first/last sightings.
The [current evidence record](server/benchmarks/object-search-experiment-2026-09-14.md)
documents the first usable [offline proposal/descriptor experiment](server/docs/object-search-experiment.md),
safe public/private aggregates and a passing 100-image genuine-model Go CLI/TLS
smoke with independent exact-query checks. Production stays Base224 full; no new
history endpoints, database object associations or user confirmation are added.
New models require explicit acquisition and verified local-only safetensors loading
under separate byte/runtime identities. No new pip dependencies are added.
Authorized/licensed private inputs were used; the narrow source-clip PTS scan leaves
canonical content/frame-zero and independently reproducible licensed acquisition
unestablished. Official VQ2D evaluation was not run. Bounded proposal tracklets do
not establish stable identity, continuous presence or a population estimate.
The [dated main-verification report](server/docs/retrieval-main-verification-2026-09-10.md)
retains pre-hardening local checks and genuine-model Go/PostgreSQL CLI/HTTPS evidence.
Server-source extraction passed with provisioned dependencies; hosted CI, PR/merge,
release, deployment, Android/device and production gates remain pending. Local
verification is not security certification.

## Reporting

A dedicated private reporting channel has not been established yet. If the
hosting platform offers private vulnerability reporting for this repository,
use it. Otherwise, ask the maintainer for a private contact without posting
exploit details, credentials, recordings, or identifying information publicly.
Establish and publish a private contact before the first external software release.

## Sensitive Material

- Keep archives, metadata exports, database dumps, backups, embeddings, query/history
  exports, downloaded public datasets, model weights and raw reports outside Git.
- Do not commit pairing tokens, cloud API keys, signing keys, or real `.env` files.
- Treat OCR text, image crops, screenshots, audio, and logs as potentially private.
- Use synthetic examples for ordinary tests/issues; public experiments must retain
  source/license provenance and keep downloaded artifacts outside Git.
- Review diffs and staged files; ignore rules are not a secret scanner.

If a secret is exposed, revoke or rotate it. Removing it from the latest commit
does not remove it from existing clones or history. Coordinate any history
cleanup rather than rewriting shared history without agreement.

## Design Requirements

Recordings remain local by default. Cloud analysis must be explicit and
disableable. Authentication does not replace transport encryption: device/server
communication must protect both identity and data in transit.

ADB wireless debugging is a development facility, not the application transport.
Do not expose debugging or application ports to the public Internet by default.

Lock-screen access to archive results has a privacy consequence independent of
the Android device PIN. Resolve and document that policy before exposing private
history while the device is locked.
