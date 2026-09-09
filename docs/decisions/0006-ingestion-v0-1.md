# ADR 0006: Local-First Ingestion 0.1.0

Status: Accepted — implementation direction, not security certification

Decision recorded: 2026-09-09, following user approval of the first executable
contract and minimal Go server. Contract **0.1.0 is unreleased**. Independent review,
final-revision verification and applicable CI remain merge gates.

## Context

[ADR 0005](0005-server-foundation.md) proposed a Go core and Python inference after
the original Python/FastAPI product baseline. The first useful increment is
authorized, exact original retrieval after safe retry/restart, independent of
Android sync, ML or cloud availability. This decision adopts Go for that concrete
increment without accepting or implementing the whole proposed pipeline.

## Decision

- **Autonomous components:** `contracts/` owns the canonical OpenAPI 3.1 and JSON
  Schema 2020-12 definitions and executable checks. `server/` uses Go 1.26.4,
  PostgreSQL 15 and a private Linux filesystem root. It embeds a controlled contract
  snapshot with version, source provenance and SHA-256 hashes. Ordinary component
  builds/tests do not read siblings; root assembly explicitly compares canonical
  bytes and runs both components when either changes.
- **Local trusted bootstrap:** HTTPS only, TLS >=1.2, loopback by default and
  explicit LAN bind. Local CLI commands migrate, create archives, issue single-use
  invitations (default/max 10 minutes) and revoke devices. Trusted manual invitation
  transport carries the server origin and DER leaf SHA-256 pin; bootstrap checks
  certificate name, validity, pin and live verified TLS. No QR UI is implemented.
  Credentials are random bearer tokens stored only as hashes, scoped to an archive.
  Lost successful pairing responses require revocation/re-enrollment; certificate
  rotation requires trusted re-bootstrap. Upload authorization is rechecked before
  commit; already-authorized downloads may finish after revocation.
- **Bounded ingestion:** atomic immutable metadata batches of 1–100 frames, at most
  1 MiB JSON; full JPEG upload/retry up to 16 MiB. Verify exact SHA-256/byte length,
  JPEG markers/header and bounded dimensions/pixels without re-encoding originals.
  Optional absent/null legacy metadata normalizes consistently. Canonical protocol
  definitions own exact fields, limits, error/retry mappings and compatibility.
- **Persistence and isolation:** separate local migration/admin and nonowner runtime
  database roles; transaction-local owner context and content-table RLS. The runtime
  rejects unsafe privileges. One process/data root per database; filesystem
  publication/fsync precedes the final metadata and one initial **pending** job
  commit. Restart reconciles valid pending published originals. These controls
  trust the local root/database operator and runtime database credentials; they
  do not prevent a privileged operator from accessing plaintext.
- **Receipt and recovery meaning:** stable receipts record historical durable
  commitment under the declared Linux/filesystem/PostgreSQL settings, not current
  availability, backup, ML completion or phone-eviction permission. Original reads
  verify current bytes and fail closed on corruption; `/healthz` is process liveness.
  Generic errors must not leak credentials, payloads, SQL or filesystem paths.
  Corrupt known pending originals block startup for operator investigation;
  unknown/staging entries are preserved and counted, not automatically deleted.
- **Operator-owned at-rest protection:** encrypted disks and coherent encrypted
  backups are prerequisites to be provisioned and checked by the operator. The app
  neither implements E2EE nor attests encryption. Recovery/certificate keys need
  separate secure custody; credential reset cannot recover lost encryption keys.
  Backup and clean-node restore procedures need operator verification.

## Consequences and Evidence

Go is now the ingestion implementation language. Python/ML, queue consumption,
search, cloud integration, Android synchronization, automatic repair/retention and
phone eviction remain unimplemented. No GPU capability, production shared-service
readiness or cryptographic protection from administrators is established.

[Server quality](../../server/docs/quality.md) owns required Linux/PostgreSQL,
TLS/CLI, two-owner, concurrency, fault/restart, conformance and race checks, plus
the >=85% pure `internal/protocol` statement-coverage gate requiring independent
review. [Contract quality](../../contracts/docs/quality.md) owns schema/OpenAPI,
fixture, boundary and relationship checks. Schema success alone cannot prove
runtime authorization or durability. [Root CI](../../.github/README.md) orchestrates
those commands, read-only canonical snapshot parity and the server-context Docker
build; wiring is not evidence of a successful hosted run.

Component builder results require main-agent reruns and independent review at the
final revision. Synthetic faults and process crashes do not prove physical
power-loss behavior, restored-backup recovery, device sync or production deployment.
Use the component [setup](../../server/README.md),
[storage](../../server/docs/storage.md) and
[normative protocol](../../contracts/docs/protocol.md) for operational detail.
