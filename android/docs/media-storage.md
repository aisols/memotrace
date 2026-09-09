# Profiles And Media Storage

Implements ADR 0004; debug versionCode 2/versionName 0.2.0. No toolchain upgrades.
The [README](../README.md) lists all six immutable profile IDs and the experimental
1440x1080 Q90 default. This document describes intent and implementation, not new
device evidence. The dated v1 verification report remains historical.

## Boundaries And Schema

After consent/permissions, accepted Start reserves the process-wide slot and
freezes CaptureSession/profile BEFORE asynchronous service delivery. The private
service must consume that in-memory UUID token, not a profile supplied in an
intent. Second Start/profile changes are rejected during reservation; failed
launch/Pause releases it. A process restart cannot replay a lost reservation.
If UI Pause cancels a reservation synchronously, it queues no service command.
Otherwise UI/notification Pause carries the target session UUID. Notification
PendingIntent identity is also session-specific, so an old token cannot stop a
new session. Rejected/unknown commands use `stopSelf(startId)`, and internal stops
use the latest handled start ID, never unconditionally stop a newer queued Start.
Album paths are
`Pictures/MemoTrace/<profile>/<profile>_<yyyyMMdd-HHmmss>Z_<session-UUID>/` with UTC
time and canonical UUIDs. New filenames are canonical UUID `.jpg`, independent of
wall-clock collisions. Gallery's leaf album name includes the profile identity.

FrameStore owns private SQLite and commit/recovery orchestration; MediaDestination
isolates ContentResolver, MediaProvider and caller-owned output. JpegMetadata
streams hash/count and reads JPEG bounds only. LegacyArchive handles shipped v1
files. CameraX alone encodes captures; the application never creates/rescales a
Bitmap for capture. CameraX can do necessary cropping, orientation and EXIF work.

`no_backup/recorder/index.sqlite` uses schema v2, synchronous FULL, DELETE journal
and a non-destructive corruption handler. One transaction adds `locator_kind`
(legacy/media), `uri`, `relative_path`, `profile_id`, `session_id`, requested
width/height, `jpeg_quality`, negotiated width/height, actual width/height,
`validated`, `availability`, then user_version=2. All v1 fields/other tables are
preserved. Existing rows default to legacy/private with null dimensions and URI.
No private original is exported, exposed or deleted. Legacy viewing is explicitly
unavailable; migration does not invent dimensions or reinterpret v1 settings.

The existing integer `state` has three meanings: 0 pending, 1 committed, and
2 (`QUARANTINED`) terminal unvalidated uncertainty. Quarantined rows retain
`availability=CLEANUP_UNPROVEN`, request/profile/session identity, expected path
and any recorded/correlated URI. They are not historical successful captures.
No additional table/column or destructive migration is required for this state.

## Commit And Recovery

1. Check the 128 MiB free-space reserve, then commit `state=0, validated=0` with
   UUID/path/request/session metadata BEFORE inserting MediaStore output. The
   reserve is not a reservation; later ENOSPC still causes a storage error.
2. Insert `IS_PENDING=1` into Images on `external_primary`, persist the URI, then
   verify exact owner/path/name and pending state. Open a PFD (`rw`) and expose
   its AutoCloseOutputStream to CameraX as a borrowed stream.
3. Only after terminal callback AND disk barrier: flush, native Os.fsync, close
   the output, stream SHA-256/bytes, validate SOI/EOI and decode bounds (not a full
   image decode). Commit hash/bytes/actual dimensions/save time and `validated=1`.
4. Publish with owner/path/name/IS_PENDING predicates; require one updated row.
   A subsequent query still reporting pending is an error. Absence/access loss
   after successful update is instead an external availability change: commit
   historical `state=1` with MISSING/INACCESSIBLE (or changed/trashed) status.

There is no SQLite/MediaStore atomic transaction. Errors from insert/query/open,
write/fsync/close/read, publication or index commit are not successful captures.
Post-acknowledgement availability changes do not turn a successful publication
into a storage failure or stop recording.
Caller-owned resources close after drain even on errors; runtime storage errors
disable Start pending process-start recovery, never recovery alongside a writer.
Typed cleanup uncertainty alone is different: after an acknowledged abort/failure
and the writer barrier, abandon durably quarantines the unvalidated record. Pause
then remains PAUSED/ready for another Start; the aborted frame is never a save.
ERROR_FILE_IO retains its storage-failure result even if quarantine succeeds.
Actual write/fsync/close, DB, provider-operation and unrelated stat errors remain fatal.

| Crossing | Recovery before camera |
| --- | --- |
| Staged DB row, provider row absent | Preserve as QUARANTINED/CLEANUP_UNPROVEN; allow startup/new sessions, never claim artifact cleanup |
| Insert applied before URI persisted/insert response lost | Find exact owner/path/UUID name; ambiguous matches fail closed |
| URI saved, open/write/hash/sync but not durably validated | Prove unlink before removing row; missing/unavailable unlink evidence becomes a retained quarantine tombstone |
| Already quarantined | Do not query/delete/retry its artifacts; retain provenance and expose its separate count |
| Validated, still pending | Rehash/recheck durable bytes and bounds, publish and commit recovered |
| Published before DB commit/provider applies update then throws | Never delete; commit historical row, reconcile availability |
| Validated URI absent | Retain durable metadata as recovered MISSING tombstone; see ambiguity below |
| DB failure/provider query or permission failure/ownership mismatch/invalid validated data/publication or batch failure | Remain fatal; retain evidence, do not blanket-convert errors into quarantine |
| Already committed | Keep historical metadata; reconcile without deleting any original |

Absent validated output is ambiguous: publication followed by external deletion
cannot be distinguished from disappearance while pending. Preserve a MISSING
tombstone and allow recording rather than pretending it is available or blocking
forever. Historical count includes tombstones. An unexpectedly published but
unvalidated row is retained and fails closed; the protocol never publishes there.

Unvalidated missing output is different: without a surviving inode witness we
cannot distinguish never-inserted, externally removed, or renamed-but-still-linked
output. Startup recovery now quarantines that individual old record rather than
blocking every subsequent start. This fixes the earlier overly strict recovery
policy, including death before insert, insert failure creating nothing, and a
provider row whose file has not materialized before first open. Recovery never
opens a write handle to manufacture cleanup evidence.

Only known absence or `UnlinkUnprovenException` while cleaning an old unvalidated
record takes this path. A `FileNotFoundException` opening the read-only unlink
witness becomes that typed uncertainty; DB corruption/update failures, provider
query/security/batch failures and bad validated pending data still propagate.
The quarantine DB update itself must succeed. There is no broad exception catch.
Current insert/write or genuine cleanup failures still stop recording and drain.
After writer drain, abandon catches only typed unlink uncertainty and quarantines
it without invalidating storage readiness. Full recovery remains startup-only,
never against a live writer; this does not add recovery alongside capture.

All saved counts/last-save/image queries select state=1 only. Quarantine count is
reported separately (`quarantined_count` in the UI), is not viewing eligibility,
and remains stable across startup/return checks. No future automatic cleanup or
retry targets state=2, even if its file later materializes or disappears. Identity
and possible artifacts remain for future authorized diagnosis, without path scans,
index erasure, or a claim that cleanup succeeded. Validated-missing historical
tombstones keep their existing committed/MISSING semantics.

Legacy pending renamed `.jpg` rolls forward using v1 framing/hash. Recognized v1
partials/scratch can be removed; missing/length-changed/unindexed private originals
still fail closed without deleting evidence. Recovery after prepare is rejected.

## Provider Deletion Contract

A plain `ContentResolver.delete` selection is NOT an atomic deletion guard.
AOSP `android-16.0.0_r1`, MediaProvider commit
`d3bb9ac8e6daab448635eaa30e85e2e8d8cbad8e`, confirms:

- [MediaProvider.java](https://android.googlesource.com/platform/packages/providers/MediaProvider/+/d3bb9ac8e6daab448635eaa30e85e2e8d8cbad8e/src/com/android/providers/media/MediaProvider.java),
  6955-6972 selects candidates, deletes filesystem content, then deletes DB rows
  by ID without reapplying the caller selection. SHA-256:
  `ac47196ba3877c7580f57c970d59621732a7dbcb874e862959649a383cb7bd62`.
- The same source's 9043 performs `Os.rename` before the database update at 9152
  (`updateAllowingReplace` acquires its transaction at 9275). A publisher may
  therefore rename a pending file before another thread's batch deletes its old
  DB row/path. The publish update can then affect zero rows while the renamed
  JPEG remains linked. Neither the batch count nor an absent query proves unlink.
- Its `applyBatch`, 6032-6066, begins the volume database transaction BEFORE
  calling the superclass and only commits after all operations succeed.
- [DatabaseHelper.java](https://android.googlesource.com/platform/packages/providers/MediaProvider/+/d3bb9ac8e6daab448635eaa30e85e2e8d8cbad8e/src/com/android/providers/media/DatabaseHelper.java),
  833-842 obtains a write transaction; 906-938 reuses it for nested operations;
  867-897 ends it before dispatching accumulated notifications. SHA-256:
  `30a8dbee47a14b170aa892ecd2fc6cecc084fa78ba666b26d1ac1af96df513dd`.
- [ContentProvider.java at android-16.0.0_r1](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r1/core/java/android/content/ContentProvider.java),
  2671-2685 applies operations sequentially, with no yield. Generic providers
  do not promise atomicity; the above MediaProvider override supplies it. SHA-256:
  `31f47e1f8a0eafed09295e236d3ef19f2b94cfaf6909b1647057537fd99108ca`.

Production cleanup submits exactly an assert-query and a delete on the same item
URI, both with exact owner/path/name, `is_pending=1`, `is_trashed=0`, expected
count 1, yield=false and exceptionAllowed=false. Publication/identity DB mutations
cannot commit between the assertion and delete under this transaction. Any batch,
assertion or provider failure stops cleanup and retains private index provenance;
there is no plain-delete fallback. Product code never deletes published originals.

Before that batch, `watchUnlink` opens a read-only PFD. Its observations are explicit:

- PROVEN_UNLINKED: initially linked regular file, same device/inode, now nlink=0.
- STILL_LINKED: the same valid regular inode still has links; it may be an orphan.
- UNKNOWN: retained-descriptor fstat ENOENT, unusable original observation,
  nonregular/proxy descriptor, or changed inode. ENOENT is never treated as proof.

The [failed A33 run](a33-gallery-failure-2026-09-09.md) demonstrated that Samsung/FUSE
can return ENOENT for a retained descriptor after deletion. Rename ambiguity means
that this cannot be equated to unlink. Only ENOENT receives that mapping; EBADF,
EIO, EACCES and other stat errors propagate with their original errno. A missing
read-only open remains typed uncertainty, except when its cause identifies a
non-ENOENT errno (that original failure is preserved). UNKNOWN/STILL_LINKED prevent successful
cleanup and retain private provenance. The descriptor closes on all outcomes. This is bounded
to the current cleanup, not an additional JPEG copy or growing capture-time FD
archive. Opening read-only never creates a replacement at an already moved path.

This is an AOSP source contract, not a claim that the Samsung/OEM provider has
been verified. MAIN must run the actual-provider assertion and concurrent
publication/deletion regressions before accepting that device. Filesystem side
effects are not rollback-atomic with the DB; even a completed batch can leave a
renamed orphan. The witness reports rather than repairs that condition. Unsupported
OEM/FUSE unlink evidence never proves cleanup. Unvalidated uncertainty can be
quarantined at startup or after acknowledged writer drain, while true storage
failures stay fatal. Power loss also loses in-memory witnesses.
Never infer permission
to remove a published original or uncertain artifact from a failed batch.

## Pinned CameraX Contract

The existing main-thread submission/abort and FIFO barrier proof remains applicable
to the OutputStream path in `camera-core:1.5.3`. Source artifact:
<https://dl.google.com/dl/android/maven2/androidx/camera/camera-core/1.5.3/camera-core-1.5.3-sources.jar>.
ProcessingNode 140-147 rejects aborted input before enqueuing processing;
124-128 wraps the same executor with a sequential worker on low-memory devices.
RequestWithCallback 218-246 aborts on main but does not drain queued disk work.
The existing CaptureDiskQueue barrier waits for that work before completion.

JpegBytes2Disk.apply 50-60 writes scratch, updates EXIF and copies to target on the
same lane. FileUtil.moveFileToTarget 128-145 deletes scratch in finally;
copyFileToOutputStream 219-229 closes only its input, not the caller's output.
Do not use CameraX's MediaStore options: its finally publication is not our
validated-phase protocol. A dependency upgrade/output change requires re-audit.

Stream FileUtil.createTempFile 60-73 uses File.createTempFile("CameraX", ".tmp")
in Android's private app cache. Startup CameraScratch cleanup recognizes only
regular non-symlink `CameraX-?[0-9]+.tmp` there and fsyncs the directory; v1 UUID
`.part` cleanup remains in the legacy root. Temporary scratch can survive a failed
capture until process recovery; it is not a second persistent archive. Tests invoke
the pinned factory/copy path. Instrumentation never cleans earlier normal scratch.

## Availability And Privacy

Startup/Activity-return reconciliation queries indexed item URIs only, never all
Gallery. Projection explicitly includes IS_TRASHED with MATCH_INCLUDE: trash is
unavailable and ineligible for viewing, never automatically restored/deleted.
Missing, changed byte size/name/path/owner, pending or inaccessible items
get non-blocking availability status; original hash/bytes/dimensions remain intact.
Unchanged availability avoids unnecessary DB writes. Per-frame summaries do not
open N images. Full history reconciliation is deferred while reserved, recording
or draining; it runs after Pause/drain on the serial IO lane. While an idle full
sweep runs, Start is disabled with archive-checking status. Thus it cannot occupy
the capture lane behind a newly started camera and consume its 30-second watchdog.
No watchdog increase. A last-view check is bounded to that single item and can
run during recording. A fatal SQLite refresh failure immediately routes through
the service's stop/drain path; Pause remains usable while the session is open,
and a late successful save cannot overwrite the storage error or resume capture.
Last-view additionally opens/closes that one input, then ACTION_VIEW grants only
read access to one content URI via data/ClipData. Missing viewer/access failure is
explained visibly; a file may still disappear after the check. Same-size edits are
not detected without rehash, and bounds/framing validation is not full decoding.

Consent is a stable private preference `public_pictures_consent_v1`, accepted by
an accessible first-Start dialog; cancel records/publishes nothing. Service Start
also checks it. Profile preference `profile_id` updates only when ready and fully
drained; stale dialogs cannot retarget an in-flight request. Native large-font,
scroll/gesture cancellation and accessibility-click behavior remain in effect.

MemoTrace has no network or broad photo permission, but public Pictures can be
backed up/shared by Gallery/Photos/OneDrive independently. Public images may
survive uninstall/data clearing; index, preferences and private legacy files do
not. Reinstall does not restore the lost index or old app ownership.

## Verification Limits

Runner-stage retention does not protect against host APK uninstall. MAIN confirmed
the target package absent after the failed gallery run; old private fixture
ledgers must not be assumed to survive. The pinned AGP/UTP host defaults and new
pre-install retention gates are documented in [connected-test safety](connected-test-safety.md).

Unit tests generate synthetic JPEGs at runtime; provider/destination fakes exercise
crossings and resource contracts, not Android power-loss durability. Real tests
use isolated SQLite/preferences and `Pictures/MemoTrace-instrumentation/<UUID>/`.
`TestMediaNamespace` durably registers each requested name/path BEFORE insert in
private `media-fixtures-<run-UUID>` preferences, then registers the returned URI.
Cleanup enumerates that explicit ledger, not a public subtree. Lost URI responses
use only exact pre-registered identity correlation; uncertainty keeps the ledger.
Each registered fixture uses a non-yielding assert/delete batch with expected
count 1 and exact URI/owner/path/name. Only these explicit test fixtures may be
deleted after publication. Matching owner/path/UUID format alone is NOT creation
provenance: a same-owner, valid-UUID unregistered sentinel in the test subtree must
survive. No normal archive deletion, broad Gallery scan or automatic export.
Ledger entries are removed only after a retained descriptor reports PROVEN_UNLINKED,
including when the provider row has already disappeared. Native races hold one
fixture witness across both workers and drain both before examining outcomes.
UNKNOWN/STILL_LINKED retain the durable ledger and return a per-fixture residue
report, also logged as `Cleanup NOT proven` via instrumentation status. Expected
uncertainty does not throw out of test/runner cleanup. Identity mismatch, provider
operation, DB/ledger or descriptor-close failures still throw; they are not swallowed
as unknown. Witness handles always close, including errors.

Runner finish always delivers its result bundle. Expected residues append
`memotrace.cleanup.unresolved` and stream diagnostics without changing JUnit
results. Real cleanup errors set an error/shortMsg and a failed/canceled run result,
with the original cause/stack logged, instead of a process crash. An undrained
session blocks cleanup and reports a strong run error. Isolated index/preferences
are retained when residues remain. This is not a claim that every fixture was removed.
The missing-row/lost-witness regression intentionally retains its private ledger,
even though its separate delete call observed unlink; no evidence is invented
after losing that witness. MAIN must record retained ledgers/residue separately
from test pass counts. Actual orphan repair remains an explicitly authorized
manual operation, never a broad scan/delete or a plain-delete fallback.
Robolectric's fstat is a zero-filled stub: adapter unit tests inject explicit
inode/link-count facts and do not claim Android filesystem evidence.
The destination fake now creates only a row at insert and materializes its file
at openWrite. A native insert-before-first-open regression forbids output writes
during recovery and starts an isolated Application against the staged index. It
requires ready=true, zero saved images and either proven removal (eager provider)
or a retained quarantine record (lazy/unproven provider), without forcing file
creation. Its isolated ledger/index remain diagnostic fixtures; test cleanup
authority and witness requirements are unchanged.
Real camera tests require an approved nonprivate scene because fixtures are public
and independent backup may already have copied them before cleanup.

See device-verification.md for main-owned execution and same-scene benchmarking.
No builder device access, new performance claim or release publishing is implied.
