# ADR 0004: Capture Profiles And Public Pictures

Status: Accepted (user-approved prototype choice; review/device gates separate)

Date: 2026-09-09

## Context

The user wants the same scene recorded with different JPEG resolutions/qualities,
separate profile/session folders, and immediate inspection in Gallery/My Files.
The user approved public Pictures after being warned that Gallery, Google Photos
and OneDrive may upload these images independently. That conversation is not
consent for future installations: first in-app Start must obtain explicit consent.

## Decision

- Keep six immutable, versioned pure-core profiles: 4000x3000 Q95/Q80,
  1920x1080 Q90/Q80, and 1440x1080 Q90/Q80. Use 1440x1080 Q90 as an experimental
  lower-volume default, not an optimal-quality or battery-saving claim.
- Set CameraX JPEG quality and ResolutionSelector, matching 4:3/16:9 aspect
  preference with closest-lower-then-higher size fallback. Record requested,
  negotiated and actual dimensions separately. 16:9 can crop the 4:3 field of view.
  Do not app-resize/re-encode; CameraX can perform its required cropping/EXIF work.
- Persist selection by stable profile ID. Reserve its session snapshot before
  asynchronous service delivery. Changes require a drained STOPPED
  session, rechecked by the application, not just a disabled UI control.
  Every Start snapshots a new profile-bearing UTC time/UUID album. Keep 2s/1s
  cadence and SHADOW-only diagnostics without automatic archive deletion.
- Store one original in app-owned MediaStore Images on `external_primary`, at
  `Pictures/MemoTrace/<profile-id>/<profile-id>_<UTC-time>_<session-UUID>/`.
  Keep SQLite authoritative/private. Publish with IS_PENDING only after durable
  validation. No second persistent JPEG/export copy, broad photo/network permission.
- Reconcile provider/index crossings without assuming a distributed transaction.
  Delete only provably owned incomplete pending images or known private scratch,
  never published originals. Pending deletion requires a non-yielding provider
  assert/delete transaction, not a plain selection. Retain metadata for externally
  missing/changed/trashed images and defer full history sweeps until idle/drained.
- Migrate shipped v1 transactionally in place, preserving other tables, rows and
  private originals. No automatic export/exposure; legacy dimensions stay unknown.
  Legacy viewing is explicitly unavailable in this slice. Existing private-archive
  consistency failures still fail closed.
- ACTION_VIEW opens the last committed public content URI with a temporary
  read-only grant and handles unavailable files/viewers. No general archive browser,
  exported provider, lock-screen bypass or background upload.

## Consequences

MemoTrace stays offline, but public originals are not a phone-only guarantee.
Other apps' backup/sharing policies apply independently. Public images may survive
uninstall/data clearing; the private index, consent, preferences and legacy files
do not. Reinstall cannot reconstruct the lost index or reclaim surviving media
ownership without a separately designed import flow.

Historical save count does not promise current availability. Scoped startup/return
metadata queries detect absence, changed size/name/path and access failures;
same-size edits need a full rehash. A provider may apply publication then throw:
the capture still reports storage failure and recovery preserves the original.

The [component protocol](../../android/docs/media-storage.md) specifies crossings,
ambiguous publication/deletion, and pinned executor/output ownership. Unit fakes
are contract evidence, not Android durability proof. Main must run isolated real
provider and six-profile camera tests with an approved nonprivate target and
independent backup settings considered. No device-performance claim follows here.
