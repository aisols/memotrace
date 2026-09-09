# Initial Ingestion Contract Design

Status: Proposed semantics for review, recorded 2026-09-09. There is no published
API, schema, contract version, or executable conformance suite. Descriptive terms
below are concepts, not selected wire field names, endpoints, or schema families.
See [ADR 0005](../../docs/decisions/0005-server-foundation.md) for proposal status
and [data protection](../../docs/architecture/data-protection.md) for trust choices.

## Ownership and First Vertical Slice

`contracts/` owns the language-neutral public protocol and persisted exchange
formats. Future OpenAPI and JSON Schema definitions here are canonical source;
server-generated documents must be checked for conformance, not separately edited.
Internal SQL, migrations, job payloads, inference IPC, filesystem layout, and
mobile UI/local database models remain implementation-owned.

Define only enough to verify:

1. Pair a device with an authenticated server and authorized owner/archive.
2. Negotiate/upload a small batch of synthetic originals and required metadata.
3. Obtain a receipt with a precisely defined durable archive guarantee.
4. Restart client/server, recover that receipt, and retrieve authorized originals.
5. Repeat safely; prove the same content/identity survives without duplication.
6. Deny another synthetic owner's upload attachment, receipt lookup, and original
   retrieval, and deny revoked credentials.

Assert byte identity and persisted outcomes, not merely HTTP success. This slice
must be implementable with a synthetic client without Android runtime or ML/cloud
dependencies. Query/evidence/voice families follow when their first feature needs
them. [Server internals](../../server/docs/design.md) will implement durability without
exposing their transaction or queue representation as a public contract.

## Identity and Authorization Semantics

Distinguish owner, archive, registered device, capture session, and frame identity.
Specify generation, uniqueness scope, persistence across restart/retry, and which
relationships are immutable. A session boundary is not necessarily a UTC day;
clock changes or multiple devices must not merge unrelated recordings.

The server derives owner scope from credentials and authorized membership. A
caller-supplied owner/archive selector may only select an already authorized scope;
it cannot assert ownership. Authenticate the specific registered device and
authorize every payload, receipt, original read, and later result/search operation.
Unpredictable identifiers and hashes are not access controls. Avoid revealing the
existence of another owner's identity or matching content through errors/dedup.

Pairing requires authenticated server bootstrap, expiry/replay resistance, device
credential issuance, and revocation semantics. QR/fingerprint/private CA and
mTLS/token selection are open decisions, not a permissive fallback to unverified
TLS. Define lost-device replacement and active-request revocation behavior.
Account/credential reset must not silently imply recovery of lost encryption keys.

## Immutable Payload and Integrity

Describe content identity using a defined byte count, digest algorithm/digest,
media/wire format and revision, associated with the frame and archive identity.
The first format should preserve exact original JPEG bytes, including original
EXIF, rather than hash decoded pixels or a server re-encoding. Any sanitized
derivative is distinct from the original. Specify digest encoding and length
units with the actual schema; no algorithm/version pin is established here.

The server independently verifies transferred bytes; it does not trust a client
checksum claim. Declared length, observed length, permitted format, and resource
limits must agree. Decide which lightweight/decoder checks precede the archive
receipt. “Checksum verified” cannot imply sharpness, complete JPEG decoding, or
successful OCR unless separately specified and performed.

If a future opaque E2EE mode is adopted, distinguish ciphertext identity from
plaintext-original identity and define authenticated crypto-format/key-version
semantics then. A relay that verifies ciphertext cannot claim plaintext JPEG
validation. Randomized encryption and retry identity require an explicit rule;
do not mandate speculative E2EE fields in the initial ordinary-processing schema.

## Time and Capture Metadata

Define units, clock origin, precision/uncertainty, optionality, and interpretation
for each time concept. Preserve evidence rather than manufacturing missing values:

| Concept | Meaning and mapping constraint |
| --- | --- |
| Request wall-clock time | Approximate capture request time; clock changes and timezone interpretation need handling; not a shutter timestamp |
| Elapsed/monotonic time | Ordering/duration within the documented session/boot scope; not UTC and not comparable across unrelated scopes |
| Save/commit time | Completion of persistence, or recovery completion if recovered; not the capture instant |
| Server receive/archive-commit time | Server-side processing observations, distinct from phone clocks and from each other |
| Camera/sensor timestamp | Only if actually available with documented origin; do not synthesize it from request or save time |

The [baseline recorder architecture](../../android/docs/recorder-architecture.md#durable-commit-protocol)
already distinguishes request wall, elapsed/session, and saved/recovered times.
That local storage representation is not an existing public wire contract. Owner
and registered-device metadata are not currently on wire: no upload exists.

Distinguish requested settings/profile from negotiated camera output and actual
saved dimensions/format. Requested resolution is not evidence of achieved size,
and the saved count is not a count of shutter actions or attempts. Optional legacy
fields may be absent/null with an explicit unknown meaning; do not fabricate IMU,
orientation, battery, exposure, or sensor metadata to satisfy a new schema. Specify
whether any proposed mandatory value can be reliably mapped from old recordings.

The concurrent Android work reportedly adds a public Gallery prototype, six
profiles, and session metadata. It is uncommitted and unverified in this baseline;
final mappings require coordination with its reviewed revision. Public Gallery
files may be changed/deleted by other applications. Freeze a stable upload source
or detect changes and verify the transferred bytes against the immutable checksum;
do not silently accept changed bytes under the old frame identity. A local content
URI is a device locator, never a durable server path. Gallery publication and
other applications' cloud upload settings have separate privacy consequences.

## Negotiation, Retry, and Restart

Negotiate which authorized batch items are missing or already committed, with a
way to retrieve established receipts after a lost acknowledgment. Retrying the
same frame identity and same bytes must return the same successful archive result;
the same identity with different bytes is a conflict and must not overwrite data.
Define conflicting immutable metadata similarly rather than silently changing
history. Same bytes under a different identity need an explicit owner-local policy;
do not confuse this with perceptual similarity or cross-owner deduplication.

Batch continuation after network interruption and client/server restart is
mandatory. Persist enough item/receipt state to avoid re-uploading already committed
items or losing the remaining queue. Expiration of incomplete staging must not
invalidate committed items. Byte-range resume inside an individual JPEG is open:
measure payload sizes, failure patterns, LAN cost, and implementation complexity
before choosing it instead of whole-file retry. Batch restart safety is required
regardless of that choice.

Define bounded batch/item sizes, declared/actual byte limits, concurrent uploads,
quotas, deadlines, and decompression limits. Treat malformed metadata, unsupported
media, oversized dimensions, checksum mismatch, decompression bombs, and truncated
uploads as explicit outcomes. Checksum mismatch permits retransmission of the
intended bytes; repeated deterministic invalid data must not cause endless retry.
Storage-full or server-unavailable responses must not pretend the archive committed.

## Receipts and Client Retention

A receipt identifies the authorized archive and frame contents, integrity result,
and protocol revision whose promise applies. Specify whether it covers individual
items or an explicitly enumerated batch, and how partial batch success is exposed.
Receipt recovery and original retrieval always require current authorization.

| State concept | What it establishes |
| --- | --- |
| Received | Bytes arrived, possibly only in temporary state |
| Verified | Defined byte/format checks completed; state precisely which checks |
| Archive committed | Verified original plus authoritative metadata are durable under the declared storage assumptions; initial work is durably recorded |
| Indexed | A specified processing/index generation is queryable, possibly with partial coverage |
| Backed up | A separately defined recoverable copy exists under a backup policy |

Only the defined archive-committed receipt, including required integrity checks,
can satisfy the upload-verification-commit condition in SPEC. A `200`, generic
“accepted,” or queued-job response alone does not authorize phone deletion. Server
local-disk durability is not backup protection, and model failure must not block
acknowledgment of an otherwise safely archived original.

Phone eviction additionally needs an explicit retention choice and implementation;
the current recorder has neither sync nor synchronized-copy eviction. Decide
whether backup is a prerequisite for a selected policy without relabeling an
archive receipt as backup evidence. A receipt is a record of the promised commit,
not proof against subsequent disk failure or a compromised server.

## Errors, Deletion, and Compatibility

Define machine-readable error categories and retry guidance before selecting HTTP
mappings: temporary unavailability/resource pressure; checksum/transfer retry;
permanent malformed/conflicting input; unsupported media/contract revision; and
authentication, authorization, or revoked-device rejection. Bound retries/backoff
and keep user-facing explanations useful without echoing secrets, private payloads,
server paths, or other owners' existence. Errors must describe actual persistence
outcomes, including how to resolve uncertainty after a disconnected response.

Original retention is independent of explicit owner deletion. Before deletion
ships, define scope, acknowledgment, derived-data/job cleanup, backup expiry, and
tombstone behavior with offline devices. A stale queue must not silently resend
a deleted archive; late work and restore must respect the agreed deletion policy.
Intentional re-import semantics and tombstone lifetime remain open, not an invented
endpoint family in this first slice.

Public protocol/schema versions are independent of app versions, SQL migrations,
and model/index generations. Establish versioning and support policy with the
first real definitions. Test supported mismatched old/new clients and servers,
including persisted recordings made before a client upgrade. Unknown optional
fields, missing legacy fields, unsupported revisions, and changed semantics need
explicit compatibility rules; never reinterpret old timestamps/checksums silently.

Provide synthetic positive/negative examples and conformance expectations for
successful ingest/read, lost ACK, restart, duplicate/conflict, malformed bytes,
revocation, cross-owner denial, and legacy optional metadata. Consumers use pinned
artifacts or controlled local snapshots with source revision, version, and checksum.
Ordinary isolated builds must not import sibling `contracts/` sources or contact a
live server for generation. Schema validation alone cannot prove server durability;
component tests and later cross-component tests must verify actual outcomes.

Before writing machine-readable definitions, resolve enrollment/key custody and
the precise byte/receipt promise. Resolve mobile field mapping with Android and
review error/version rules with both consumers. Keep SQL/jobs private and defer
the rest of the public API until a working feature needs it.
