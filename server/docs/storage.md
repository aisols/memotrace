# Ingestion persistence and security boundary

Implemented subset, contract 0.1.0; Linux only. Local root/operator and database
administrators are trusted. This is not encryption attestation or shared-host isolation.

## SQL ownership, privileges and RLS

The `mt` schema and version-1 migration are owned by the local migration/admin role.
`owners`, `archives`, `frames`, `jobs` have default-deny RLS keyed by
`current_setting('mt.owner_id', true)`. Runtime content operations use transaction-local
`set_config(..., true)`, disappearing on commit/rollback; no session-scoped pool state.
Startup rejects inherited table/schema ownership and privileged roles, requires RLS
on all four content tables and requires PostgreSQL `fsync`, `full_page_writes` and
`synchronous_commit` on. Every runtime connection explicitly enables synchronous commit.

Runtime gets SELECT on content/version, INSERT on frames/jobs, UPDATE only on
`frames.committed_at`, and USAGE on `mt`. It has no direct privileges on devices or
invitations. Those bootstrap tables intentionally have no owner-context RLS: auth
must establish scope before content queries can use it. Only narrowly granted
SECURITY DEFINER functions with fixed `search_path=pg_catalog`, qualified names and
no dynamic SQL cross that boundary:

- `authenticate(hash)`: active credential's owner/archive/device identities;
  SHARE-locks the device row for the transaction.
- `redeem(hash,new_id,new_hash,name)`: locks/consumes an unexpired invitation and
  inserts its device atomically, returning scope.
- `recovery_owners()` / `recovery_archive_owner(archive)`: startup scope identities,
  then ordinary RLS-scoped transactions for reconciliation.

PUBLIC has no schema/table/function privileges. RLS is intentionally not FORCEd
against the administrative owner: local CLI/definer functions need declared admin
and bootstrap access. Runtime must never inherit that role. Runtime SQL credentials
are a trusted application boundary: an attacker holding them can invoke bootstrap
functions and set scope. RLS defends missing/mis-scoped queries, not a compromised
application/database credential or trusted administrator.

## Durable commit sequence

1. Authenticate and register the complete batch's immutable expected metadata in
   one durable SQL transaction. Normalize nullable optionals; retain registering
   device. Lock keys in sorted order to avoid inverse-lock overlapping-batch deadlocks.
   Validate Unicode scalar escapes before lossy JSON decoding and reject NUL in
   canonical user-text fields before registration SQL; preserve valid scalar bytes
   without normalization/replacement. Invalid text cannot partially register a batch
   or consume an invitation.
2. Authenticate/read the registered metadata and release that transaction. Stream
   at most 16 MiB + 1 detection byte to private random `.stage-UUID`, computing SHA-256.
   Validate exact length/hash, SOI/EOI, JPEG DecodeConfig, each dimension 1..16384 and
   <=40,000,000 pixels. Preserve every original byte, including EXIF.
3. Fsync stage. Reauthenticate after streaming, SHARE-locking the active device,
   then lock the frame FOR UPDATE. Revocation's local UPDATE serializes with this
   transaction; completed revocation cannot slip through to a new upload commit.
4. Publish with an atomic hard-link insertion, which cannot replace the final
   `ARCHIVE_UUID_FRAME_UUID.jpg`. Stage/original are on one filesystem and share
   the durable inode. Existing paths independently validate. Fsync root directory.
5. In that frame-locked SQL transaction persist commit time and one unique initial
   pending `(archive_id,frame_id)` job, then synchronous COMMIT. Only afterwards
   serialize the receipt. Unlink stage during cleanup; a crash can leave a harmless
   extra hard link, preserved/reported on startup.

There is no worker, lease executor, Redis, inference, full decode or fake completion.
The receipt's integrity label is exactly `sha256-byte-length-jpeg-header`.

## Filesystem assumptions and recovery

Operator pre-creates a private absolute root on a local Linux filesystem supporting
atomic hard links, file/directory fsync and flock, e.g. appropriately configured
ext4/XFS. Root and existing ancestor chain are synced at startup. Flat server-generated
names avoid archive-directory creation races. Access stays beneath `os.Root`;
originals use `O_NOFOLLOW`, `O_NONBLOCK` and regular-file checks. Canonical UUIDs
precede pathname generation. Root/parents are trusted against local replacement;
symlinks are not caller-controlled capabilities. Files/lock are 0600, root 0700.
No NFS/object-store/physical-power-loss guarantee is claimed.

The root flock spans recovery, serving and shutdown. Configure one root/process
per database; the root lock cannot coordinate distinct roots pointed at one database.
Recovery pages pending registrations, validates existing published originals,
fsyncs their files/directory again and idempotently completes frame/job SQL. Missing
bytes remain pending. Corrupt/irregular known pending originals block startup and
remain preserved. An inventory pass counts unknown originals/records and abandoned
stages without deleting anything or logging identities/paths. Inspect them locally
under trusted operator procedures; never substitute unknown bytes for expected content.
Large-root scan duration is not benchmarked.

Failed COMMIT/lost response means uncertain commitment: receipt lookup or safe repeat
resolves historical success versus pending. A post-publication process crash rolls
forward on restart. ENOSPC, file/directory fsync or publication failures cannot create
a premature successful receipt. Dependency-injected faults and process exit hooks
are test-only; production exposes no CLI/environment/request activation.

Original GET captures and validates a bounded private byte copy before success headers,
avoiding a second-read mutation window. Missing/damaged committed originals return
409 `integrity_error`; historical receipt remains available. Automatic repair,
deletion or phone-eviction policy is not implemented.

## Resource/lifecycle limits

Thirty-two accepted connections (including TLS handshakes/idle clients), eight
admitted requests, at most two pairing operations, twelve DB connections,
1 MiB JSON, 16 MiB JPEG, JSON nesting <=16. Overload is retryable 503; health liveness
is independent of admission. Request context 90s; HTTP header 5s/read 90s/write 100s/
idle 30s; headers 8 KiB. DB connect 5s, statements 15s, locks 10s, idle transactions
30s. Slow filesystem operations remain subject to OS behavior, but failed/timed-out
SQL transactions cannot acknowledge new commitment. SIGTERM/SIGINT allow up to 105s
to drain, then close resources. Each original GET may hold a bounded JPEG copy per
admitted request; deployment memory must exceed the working set.

TLS >=1.2 only, loopback default; PostgreSQL needs trusted local socket or verified
transport in deployment. Content, credentials, DSNs and TLS/access logs are absent.
Bearer scheme casing is ignored while credential bytes remain exact. Protected-route
401s carry the canonical Bearer challenge; pairing 401s carry the separate
MemoTraceInvitation JSON-body challenge. Local invitation TTLs are whole seconds
1..600. Expiry is stored/emitted at identical microsecond precision, preserving
fractional time rather than rounding down to a whole second, and checked before
successful output.
Diagnostics currently consist of aggregate startup inventory counts and generic
command failure, not a complete monitoring/incident system. Encryption, coherent
backups and separately protected recovery keys are operator responsibilities.
