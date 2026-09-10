# Recorder Architecture

Implements accepted ADRs 0003 and 0004, supplementing the product specification. This is
a prototype implementation, not an independent review or device certification.

## Acquisition And Ownership

`CapturePolicy` is pure Kotlin, single-owner and driven by monotonic milliseconds.
`RecorderService` owns it on the main thread. `RecorderCamera` isolates camera
side effects; the production implementation binds rear CameraX `ImageCapture`
and `ImageAnalysis` to the **service's** lifecycle, never the Activity's. Capture
is explicitly JPEG, minimize-latency mode, with an immutable CaptureSession/profile
snapshot per Start. Ordinary UI starts are fixed to `v1-1920x1080-q90`; the six
immutable profiles remain available only through the programmatic verification seam.
Matching 4:3/16:9 aspect and closest-lower-then-higher resolution
fallback are explicit; requested, negotiated and actual dimensions are separate.
JPEG quality is applied by CameraX, without application rescale/re-encode.
See the [six-profile matrix](../README.md) and [storage protocol](media-storage.md).
Camera sensor/exposure/focus/rotation metadata, where
available, remains in the returned JPEG. No preview surface or JPEG re-encoding
is introduced by application storage code.

First Start obtains explicit persistent public-Pictures consent before requesting
CAMERA and POST_NOTIFICATIONS. The service also rejects Start without that consent.
Camera consent is essential; notification denial does not silently grant camera
consent or stop a permitted foreground service. The notification warning explains
Android's active-apps visibility when notifications are denied. The service is
nonexported, uses CAMERA foreground type/permissions, posts its ongoing
notification immediately, returns START_NOT_STICKY, and has no boot restart path.

The service uses a non-reference-counted, ten-minute partial wake lock, renewed
at five minutes only while recording. Pause, timeout, camera failure and service
destruction release it. Camera open/analysis loss and in-flight work have a
30-second watchdog. OEM background policy, thermal shutdown, permission changes,
camera preemption and screen-off behavior remain required device experiments.

## Bounded Work

- The scheduler's one slot spans pending-row creation, capture, checksum/fsync,
  MediaStore publication and SQLite commit. Busy ticks are discarded; no catch-up burst is stored.
- A single application IO executor serializes recovery, commits and explicit summaries.
  The caller permits only one acquisition chain, not an unbounded task stream.
- The same application IO executor serializes session, telemetry and attempt journal
  writes with frame metadata. Sampling occurs at session start, at most about once
  per 60 seconds, on bounded thermal callbacks, and at terminal drain. Sensor reads
  are nullable and nonfatal; SQLite integrity failures stop recording.
- ImageCapture uses a separate owned serial IO executor. Terminal callbacks cross
  a FIFO disk barrier before the service can finalize/abandon or release its slot.
- CameraX analysis uses KEEP_ONLY_LATEST, requests approximately 640x480 (nearest
  supported resolution fallback), and closes every ImageProxy in `finally`.
- Only once per 250 ms are 32x24 luma samples read using row/pixel stride and crop.
  The previous sample array is bounded at 768 integers. One atomic overwrite slot
  carries the newest result to the main thread; it cannot build a main-queue
  analysis backlog. No analysis images are persisted.
- Checksums stream through a 32 KiB buffer. Captured JPEGs go to a borrowed stream, not app
  byte arrays. A successful commit returns one authoritative frame delta for global
  and current-session counts and last-frame metadata; it does not run a full summary
  query per frame. Explicit summaries use indexed SQLite state, not a growing rewritten
  JSON/day manifest. Startup/reconciliation scans remain O(archive size) and do not
  run on the normal successful acquisition path.

The callback path is one-shot even if an adapter delivers twice. Pause immediately
prevents new requests and closes the camera. Already delivered JPEG output may
finish committing; the count can increase by at most one after Pause. Late
callbacks cannot restore recording/error state or acquire another frame. A
process-wide session slot is held until the terminal callback, disk drain and
application persistence finish, even after Service destruction. An abort callback
alone is **not** proof that a writer stopped. If an OEM never returns a callback,
or disk work never drains, automatic
retry is deliberately blocked instead of overlapping a possibly live writer;
the user must stop/relaunch the process. Disk failures after Pause are still shown.

### Pinned CameraX Ordering Contract

Verified against the official
[`camera-core:1.5.3` sources](https://dl.google.com/dl/android/maven2/androidx/camera/camera-core/1.5.3/camera-core-1.5.3-sources.jar):
`CaptureNode` lines 234-258 dispatch image availability on main; lines 284-309
submit the processing packet before signalling image capture. `ProcessingNode`
lines 140-147 reject aborted inputs and synchronously enqueue disk processing.
`RequestWithCallback.abortAndSendErrorToApp` lines 218-246 sets the aborted flag
on main but does not wait for existing disk work. `ProcessingNode` also wraps the
provided executor in a sequential worker on low-memory devices (lines 124-128).

`CaptureDiskQueue` requires main-thread submission, terminal callbacks and close;
the same main thread orders CameraX input submissions and abort. Its FIFO barrier
waits behind existing processing, including the entire low-memory worker. Later
aborted packets are dropped by CameraX before submission. The service receives
completion only after that barrier. Close occurs after unbind, is asynchronous,
and shuts down the disk executor only after pending work drains; it never interrupts
a writer or waits on the UI thread. Do not change the CameraX version, capture
format or executor ordering without rechecking this contract.

The [stream-output re-audit](media-storage.md#pinned-camerax-contract) confirms
FileUtil closes its input, not our output, on the same processing lane. The store
owns the PFD/output, fsyncs and closes only after this barrier. Temporary cache
scratch is recognized separately from the legacy file-output `.part` pattern.

Results retain saved/camera-failure/storage-failure types. Delivered
`ImageCapture.ERROR_FILE_IO` always invalidates storage readiness, including after
Pause and successful partial cleanup. CameraX suppresses further processing results
after an abort; such an aborted request is never reported as a successful save.
Regression tests hold a real executor writer across an early abort, rapid service
restart and disposal, and assert that cleanup/session release waits for drain.

Each normal capture atomically creates its durable request row and pending frame row
before provider output preparation; a pre-transaction PREPARE failure gets a terminal
attempt row when SQLite remains usable. Separate
monotonic fields represent prepare completion, durable readiness immediately before
CameraX invocation, CameraX terminal callback, CameraX writer/disk-lane drain, and
final store/attempt commit. The readiness row is committed before main-thread
invocation and does not mean CameraX accepted the request. A phase is nullable only
when the attempt never reached it. Prepare failures, typed CameraX camera/file-IO
failures, cleanup/quarantine outcomes, and final-store failures remain explicit.
A drained SAVED result always follows FrameStore validation/publication even if
attempt telemetry fails; the valid JPEG remains while the journal fault stops the
service. A failed combined SAVED transaction leaves the attempt PENDING rather than
claiming STORAGE_FAILURE: startup frame recovery globally resolves it to recovered
SAVED or INTERRUPTED even if its session was already terminal. These are pipeline
timestamps, never shutter timestamps.

## Motion And Cover

Default motion evidence is mean absolute difference between corresponding luma
samples. Enter moving at >=12; remain moving through intermediate scores. Return
to baseline only after <=5 continuously for 3000 ms. Changing brightness or
camera exposure can look like motion; these thresholds need measured calibration.

`CaptureConfig` bounds baseline to 1000..10000 ms, motion to 500..baseline,
analysis to 100..1000 ms, quiet hold to 500..30000 ms, timeout to 5000..120000 ms.
Thresholds must be finite, 1..255 for entry and 0..<entry for exit. Configure in
the domain constructor, not through speculative UI controls.

Cover suspicion enters at mean <=12 and variance <=25; exits at mean >=24 or
variance >=64. It is merely a dark/low-texture heuristic, not a lens-cover
classifier. A normal dark room can be suspected. Results older than two seconds
are shown/stored as unknown. `CapturePolicy` has no cover input, storage has no
cover-dependent branch, and regression tests compare dark/light capture sequences.
Only cover diagnostics and chosen cadence/configuration are stored; transient
motion scores and sampled images are not archived.

## Historical V1 Protocol

The following describes the shipped v1 archive, retained only for safe upgrade
and legacy recovery. **New capture uses schema v4 and the MediaStore protocol in
[Profiles And Media Storage](media-storage.md)**, not this private-file protocol.
The v1-to-v2 transaction preserves existing rows, other tables and private JPEGs;
legacy dimensions remain unknown and viewing is explicitly unavailable.

The authoritative schema version 1 lives at
`no_backup/recorder/index.sqlite`. Originals are UUID-named `.jpg` files alongside
it. SQLite uses synchronous FULL and DELETE journal mode. Backup and device
transfer are disabled; the archive is additionally in `noBackupFilesDir`.

1. Check actual available disk space >=128 MiB before beginning a capture. This
   conservative reserve does not evict other applications' caches. ENOSPC after
   the check is still handled as a storage error; the check is not a reservation.
2. Commit a pending SQLite row before CameraX receives its UUID `.part` path.
3. On successful CameraX output, check JPEG SOI/EOI framing, stream SHA-256, fsync
   the file, atomically rename within the directory to `.jpg`, and fsync the
   directory. A newly created archive directory's parent is also fsynced.
4. Atomically update that row to committed with checksum, length and save time.
   Only then refresh the UI's authoritative committed count/last-save time.

| Crash boundary | Recovery before any new acquisition |
| --- | --- |
| Pending row, no output | Remove only the abandoned pending row |
| Partial/truncated output, or synced `.part` before rename | Remove abandoned `.part` and pending row |
| Death during CameraX scratch/EXIF processing | Remove only recognized abandoned CameraX scratch files, then fsync directory |
| Atomic rename completed, SQLite update missing | Validate/hash `.jpg`, roll forward the pending row, mark recovered |
| SQLite commit completed | Keep the original and row; recovery is idempotent |
| Missing/length-mismatched committed file or unindexed `.jpg` | Fail closed with archive error, never delete original/committed metadata |

Finalized originals are never automatically deleted. An incomplete or invalid
renamed original fails recovery without deletion. Committed same-size bit rot is
not proactively rehashed on every startup; recorded SHA-256 enables an offline
integrity audit. JPEG framing is not a full decoder. Device tests use generated
valid JPEGs; byte-preservation unit fixtures are synthetic framed payloads.
The SQLite corruption handler explicitly fails without Android's default database
deletion/recreation, preserving the index and originals for diagnosis/recovery.

Before the first acquisition, recovery removes regular, non-symlink files matching
`CameraX<canonical-lowercase-UUID>.part` only. This is `FileUtil.createTempFile`'s
actual 1.5.3 file-output naming (lines 60-70), using the supplied `.part` extension.
The regression obtains a name from that dependency method rather than inventing
a fixture convention, and checks repeated recovery, unrelated files, directories,
links and finalized originals. `FrameStore` rejects recovery after `prepare` has
begun; the Application performs startup recovery before enabling any camera
session. Runtime storage failure requires process-start recovery, never recovery
concurrent with a writer.

## Timestamp Semantics

Request wall time (`request_wall_ms`), effective scheduled due, and request time
(`scheduled_due_elapsed_ms` / `request_elapsed_ms`, elapsedRealtime) are distinct.
The policy emits due, request, and effective interval together, so an intentional
adaptive 1000/2000 ms transition is not an overrun; delay is `max(0, request-due)`.
Settings include a session UUID: do not compare
monotonic values across boots/sessions as universal timestamps. Neither timestamp
is claimed to be an exact shutter instant. `saved_wall_ms` is the finish-operation
wall time, not capture time. V1 renamed-file recovery uses recovery time;
v2 validated recovery preserves the already durable save time and sets recovered=1. A clock change
does not change scheduling; last-save display follows the latest committed frame's
insertion order, not the maximum wall clock (which could point at an older frame).
Session duration, request gaps, overruns and pipeline latency use monotonic values.
The serial IO lane durably records `camera_invoke_ready_elapsed_ms` before posting
CameraX invocation. It means only that MemoTrace was ready to invoke CameraX, not
that CameraX accepted or exposed the frame. Pipeline latency is request-to-final
commit; successful-save latency is writer-drain-to-final-commit. Process-death
recovery never compares next-process uptime: actual end and recovered attempt commit
times remain null, while recovery detection has a separate wall-clock field.
Battery and temperature samples retain raw Android/OEM facts; current, charge,
energy and temperature are whole-device measurements, not MemoTrace-only usage.
Private diagnostics retain those wall/monotonic facts. The exported report omits all
absolute wall and boot-relative values and converts session, sample, due, request,
phase, drain, and commit timing to offsets from that session's monotonic start.

## Persisted Intent And UI

Small SharedPreferences commits persist the fixed-profile UX revision/profile ID,
explicit public-Pictures consent,
requested recording plus a stable error
code, not resource IDs. A new process seeing requested=true displays interrupted
and waits for another visible Start; it never claims the camera is running merely
because intent was persisted. A count/status update acknowledges a save only
after durable commit. Recovery failure disables Start until the archive problem
is addressed and the app process restarted. Runtime storage failures also disable
Start until process-start recovery has reconciled any pending file commit. Missing
or changed older public images instead retain non-blocking historical status. Camera
failures allow manual resume after their outstanding callback has drained.

`TremorButton` uses pure `TapGesture`: DOWN anchors the original button, movement
is measured from that anchor with a 24 dp radial slip allowance, and only UP can
execute once. Moving past the allowance, system CANCEL, extra pointers, disabling
or detaching cancels irreversibly until a new DOWN. The button does not prevent
ScrollView interception: its platform vertical drag threshold wins and sends
CANCEL, even if the pointer subsequently returns. Therefore vertical tolerance
inside a scrollable area is limited by the platform's drag threshold. No neighbor
retargeting, long-press action or cumulative tremor-distance penalty is introduced.
`performClick` remains native for accessibility and keyboard activation. Both
Start/Pause controls remain in stable positions with >=88 dp minimum height,
large Russian text and high contrast. System bars/cutouts have explicit insets;
wrap-content controls and a fallback ScrollView avoid large-font clipping. No
activity screen-on flag, lock task mode, custom hardware keys or keyguard bypass.

The consent dialog uses native TremorButtons and a ScrollView. The normal main flow
has no profile mutation control. The last-image action opens an explicit nonexported
Activity with no URI grant or ClipData. It accepts only an AVAILABLE indexed
`content://media/.../images/media/<id>` JPEG, verifies provider MIME, and decodes
with ImageDecoder on its own worker. Platform orientation handling, bounded sampling
and FIT_CENTER avoid a second capture copy and avoid cropping.
Public files may be backed up independently by Gallery/Photos/OneDrive; the UI no
longer promises that images stay only on the phone.

Full history reconciliation runs only before capture or while paused/drained;
an in-progress idle sweep gates Start and a request while recording is deferred.
The single-item viewer check remains available during recording. Fatal refresh
SQLite errors synchronously request service stop/drain and remain terminal even
if an already captured frame later commits. The accepted Start profile/session
is reserved on main before service delivery; the service consumes its private
one-use token and cannot replay it after process death. See media-storage.md for
the AOSP provider transaction audit, fixture provenance ledger and trash handling.

Pause targets a session UUID, including unique immutable notification intents;
canceling an unconsumed reservation queues no stale generic Pause. All service
stop requests are start-ID-aware. Pending cleanup requires physical unlink
evidence from a retained descriptor in addition to its provider batch. At startup,
unvalidated missing/unproven records become terminal quarantine tombstones, with
retained private provenance and a separate diagnostic count, not successful saves.
They do not block new sessions or get retried/deleted automatically. Genuine DB,
provider and current-write failures remain fatal, as does invalid validated data;
provider rename-before-SQL-update can otherwise leave a linked JPEG orphan.
See media-storage.md for conservative recovery limits and native residue reporting.

The nonexported diagnostics Activity reads only one current/latest session from
private metadata. It never performs Gallery reconciliation or opens images. It loads
once on entry and does no periodic full attempt reload while OPEN; the OPEN-to-closed
transition triggers an immediate full refresh. Report export is disabled until Pause
completes the outstanding frame, final sample and terminal transaction. An
application-wide reservation then disables Start from before report acquisition
through picker cancellation/failure or confirmed output close. SAF
`ACTION_CREATE_DOCUMENT` writes a deterministic four-entry ZIP with report-local
ordinals and session-relative timing offsets on a separate export executor. Absolute
wall/boot timestamps and persistent/media identifiers are omitted. Activity
destruction during an active provider write does not release the reservation early;
stream completion/close does. Stream-close success is required before the UI reports
completion.

The failed A33 gallery run exposed retained-descriptor fstat ENOENT, not a reliable
POSIX unlink signal on that FUSE implementation. UnlinkStatus is now tri-state;
ENOENT means UNKNOWN, while unrelated errno failures remain errors. After a camera
abort/failure and the existing writer barrier, only typed cleanup uncertainty is
quarantined without disabling the next Start. It never turns the aborted frame
into a saved image or hides ERROR_FILE_IO. Runner cleanup returns/logs expected
residues and preserves normal test completion; real cleanup failures remain strong
run errors. See a33-gallery-failure-2026-09-09.md; no new device pass is claimed.
