# Security Policy

## Current Status

MemoTrace has no released or supported software versions yet. The repository
contains an early local-only Android recorder and an executable, unreleased
Go ingestion server with contract 0.1.0. It is not a production-ready system.
The recorder requests no network permission and disables backup; it does not yet
synchronize its archive. The broader design includes controls not implemented by
this slice. Independent review and final-revision verification remain required.

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
shared-service readiness. ML consumers, cloud analysis and Android synchronization
are unimplemented. The [accepted slice decision](docs/decisions/0006-ingestion-v0-1.md)
records implementation direction, not security certification.

## Reporting

A dedicated private reporting channel has not been established yet. If the
hosting platform offers private vulnerability reporting for this repository,
use it. Otherwise, ask the maintainer for a private contact without posting
exploit details, credentials, recordings, or identifying information publicly.
Establish and publish a private contact before the first external software release.

## Sensitive Material

- Keep archives, metadata exports, database dumps, and backups outside Git.
- Do not commit pairing tokens, cloud API keys, signing keys, or real `.env` files.
- Treat OCR text, image crops, screenshots, audio, and logs as potentially private.
- Use synthetic examples for issues, tests, and demonstrations.
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
