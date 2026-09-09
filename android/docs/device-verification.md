# Recorder Device Verification

The [2026-09-09 profile evidence](profiles-verification-2026-09-09.md) records
MAIN's subsequent 10/10 native passes at `ceef24e` and `6445bad`, post-host retention,
manual UI/new-photo checks and unresolved cleanup uncertainty. This is dated
evidence, not a pass for future revisions or a controlled same-scene benchmark.
The [initial A33 gallery run](a33-gallery-failure-2026-09-09.md) remains a failure:
2/10 passed, 8 failed, zero skipped, then runner cleanup crashed. Do not reuse the
old v1 pass as new-profile evidence; the implementation owner did not access the device.

After the initial failed run, MAIN confirmed the target package absent after host
teardown. AGP/UTP default uninstall can erase private ledgers despite runner
isolation. The component now enforces APK retention and disables incompatible-APK
uninstall; read [connected-test host safety](connected-test-safety.md) before any
rerun. Do not claim the earlier device ledgers still exist.

**Only the main agent/operator performs this procedure.** Implementation did not
access ADB or install/launch on the phone. Do not interpret assembled APKs or
Robolectric tests as hardware evidence. Reference: SM-A336B, Android 16/API 36.

## Identity And Build Outputs

- Application ID: `org.memotrace.recorder`
- Profile/public-storage build: versionCode `2`, versionName `0.2.0`.
- Launcher: `org.memotrace.recorder.ui.MainActivity`
- Service: `org.memotrace.recorder.capture.RecorderService` (nonexported)
- App APK: `app/build/outputs/apk/debug/app-debug.apk`
- Test APK: `app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk`
- Runner: `org.memotrace.recorder.test/org.memotrace.recorder.IsolatedTestRunner`
- Resource prefix: `org.memotrace.recorder:id/`
- IDs: `start_recording`, `pause_recording`, `record_status`, `saved_count`,
  `last_saved`, `capture_interval`, `cover_shadow`, `recorder_scroll`.
- New IDs: `select_profile`, `negotiated_size`, `session_folder`, `last_file_details`,
  `view_last`, `profile_reference`, `profile_compression`, `profile_wide_90`,
  `profile_wide_80`, `profile_compact_90`, `profile_compact_80`, `consent_accept`,
  `dialog_cancel`, `dialog_scroll`.
- `quarantined_count`: separate old-unvalidated/cleanup-unproven diagnostic count;
  excluded from saved/available image totals and not a global Start blocker.

Do not add debug exports or direct start-recording intent arguments for automation.
Starting the launcher does not grant recording consent. Tap the real Start control.

## Local And Instrumented Gates

After independently repeating the README's local command, pause any existing
recording and place a synthetic target in view. Instrumentation temporarily
replaces the normal app process; its Application uses UUID-isolated cache storage
and preferences, never `no_backup/recorder` or `record_state`. Tests clean their
own data only with verified unlink, otherwise retain/report provenance. MediaStore output uses `Pictures/MemoTrace-instrumentation/<run-UUID>/`
and an explicit private per-run fixture creation ledger, never normal Pictures/MemoTrace.
These are runner-stage protections only; host APK/data retention must also pass
the independent no-device safety gates. The default connected command below is
guarded; explicit flags and direct `adb install -r` / `am instrument` commands,
including strict result interpretation, are in the host-safety document.
Names/paths are registered before insertion and returned URIs afterward. Cleanup
only visits registered identities/URIs and uses non-yielding assert/delete batches;
a same-owner valid-UUID sentinel in the same public subtree must survive. No
subtree-wide query/delete is cleanup authority. Lost responses retain private
`media-fixtures-<UUID>` provenance until precisely reconciled.
Row absence and fstat ENOENT are not physical-unlink proof. Cleanup distinguishes
PROVEN_UNLINKED, STILL_LINKED and UNKNOWN. Only the first permits ledger removal.
The race test drains both workers before examining that evidence; unproven cleanup
returns a residue report, retains its ledger and emits `Cleanup NOT proven` in
instrumentation status. The lost-witness test
intentionally retains a private diagnostic ledger. Record these reports even if
all assertions pass; do not describe the run as residue-free. Do not scan/delete
other files to make cleanup appear successful. OEM/FUSE inability to supply valid
evidence is an UNKNOWN outcome to retain/report, not a skipped assertion or unlink
claim. EBADF and other real errors remain failures. Expected residues must not
crash runner finish; look for `memotrace.cleanup.unresolved` in final results.
Real cleanup errors set a failed result with shortMsg/stack diagnostics. Preserve
all test failures and residue reports; test success and cleanup completion differ.
An unresolved outstanding callback leaves its isolated pending output/index for
diagnosis rather than deleting a live writer. Interrupted test namespaces can be
identified by UUID; any later cleanup must remain equally precise.
Test frames are public: obtain approval for the nonprivate scene and check
Gallery/Photos/OneDrive backup settings before running. Cleanup cannot retract an
independent cloud copy. Do not broadly delete Pictures/MemoTrace to reset tests.

**Initial prerequisite:** the operator must turn on and unlock the phone using its
normal authentication immediately before the run. A secure keyguard must not be
showing. The test runner does not wake or unlock the device, bypass its PIN, dismiss
keyguard, or change screen-timeout/system settings.

Instrumentation only adds `FLAG_KEEP_SCREEN_ON` to started MainActivity windows
to avoid automatic timeout during UI assertions, including after recreation.
It clears the flag on STOPPED/DESTROYED and clears remaining tracked windows and
unregisters the callback when the runner finishes. Production activities have no
such flag. No test wake lock is acquired. The FGS test explicitly checks that the
flag is absent after Activity stop and waits for two new saves from that point;
normal screen-off/lock behavior remains possible during this background phase.
If the device locks during that phase, the operator must unlock it normally before
retrying; do not weaken assertions or skip the test.

```bash
# From android/, main agent only; select the currently authorized endpoint.
export ANDROID_SERIAL='<CURRENT_DEVICE_ENDPOINT>'
./gradlew :app:connectedDebugAndroidTest
```

Ten tests must run, none skipped: real MediaStore synthetic JPEG/recovery/decode,
UI recreation/idle Pause, foreground capture across Activity stop, and six real
camera profiles, plus six MediaProviderDeviceTest cases: batch assertion on
published/moved items, lost-insert-response/allowlist sentinel, concurrent
publication/pending deletion with physical unlink evidence, missing-row/lost-witness
ledger retention, real trash/restore availability, and insert-before-first-open
Application recovery. The latter requires readiness with zero saved frames and
either proven removal or a retained quarantine tombstone on eager/lazy providers;
it never creates a file to make recovery pass and preserves its isolated ledger/index.
MAIN's dated executions are linked above; compilation and the AOSP source audit
alone do not establish Samsung provider behavior. The six-profile test records
requested Q/size, negotiated stream,
actual bounds and bytes under log tag `MemoTraceTest`; Q is a configured request,
not proof of a firmware encoder's internal quantization. Record failures, including camera/permission
or filesystem failures; do not weaken tests to accommodate unsupported hardware.
The camera test activates the real Start/Pause controls using accessibility
ACTION_CLICK and asserts native Button nodes and visible, non-hidden ancestors.
Do not run `pm clear`, uninstall the recorder, or remove its archive to reset tests.

### First Device Attempt

Main-agent report: the first real `connectedDebugAndroidTest` run passed the
storage test but failed the two UI/capture tests with `NoActivityResumed` and an
ActivityScenario left STOPPED. The main agent found the screen off after timeout
and secure keyguard showing. This attempt was environment-blocked, not evidence
of an application defect or a passed hardware recorder gate. The test-only window
fixture above was subsequently retried by the main agent after normal user unlock:
3/3 passed, none skipped. See the [2026-09-09 main-agent evidence](verification-2026-09-09.md)
for that retry, the separate manual screen-off observation, artifact identity and
remaining limitations. The implementation owner has not accessed the device.

## Manual Recorder Smoke Test

```bash
DEVICE="$ANDROID_SERIAL"
adb -s "$DEVICE" install -r app/build/outputs/apk/debug/app-debug.apk
adb -s "$DEVICE" shell am start -n org.memotrace.recorder/org.memotrace.recorder.ui.MainActivity
```

Use an on-device UI automation client keyed by the resource IDs above, or inspect
the hierarchy with `adb -s "$DEVICE" shell uiautomator dump /sdcard/memotrace-ui.xml`
and retrieve it into a private evidence directory outside Git. Coordinates vary
with resolution, navigation and font size; do not hardcode them in the application.

1. Initially expect archive checking, then paused or interrupted, never recording.
   Previously committed count and last-save time must survive relaunch.
2. Tap Start, read/accept the one-time public-Pictures warning, then grant camera
   and (preferably) notifications. Cancel the warning first to verify no capture;
   permissions retained from v1 must not bypass this new consent. Expect connecting, then
   `Идёт запись` only after a JPEG commit and count increment. An ongoing camera
   notification must expose `Пауза`. Test denial separately: camera denial must
   not capture; notification denial must show the truthful visibility warning.
3. Observe a static target for 60 seconds. Check baseline 2000 ms, growing count,
   valid full JPEGs, EXIF orientation, focus and legibility. Move the target/device
   for 30 seconds: expect approximately 1000 ms sampling, then return to baseline
   after three seconds of quiet evidence. Do not call increased cadence a blur fix.
4. Cover the lens, then uncover it and repeat in a dark room. SHADOW suspicion
   should update or be unknown when stale. **Count must keep increasing** under
   suspicion; all finalized originals must remain. Record false positives.
5. Tap Pause during capture, then rapidly tap controls. Camera/notification/wake
   lock must release; at most one already-started frame may commit. No further
   acquisition until visible Start. Repeat notification Pause and Activity recreation.
   Repeat at the largest system font/display size and in a small/landscape window:
   controls must remain fully readable/reachable through the fallback scroll, with
   TalkBack click semantics. Status changes must not shift the buttons' content positions.
   Profile and second Start must also be blocked immediately after accepted Start,
   before service delivery. Returning during recording must not trigger a full
   history sweep; after Pause/drain it may show archive checking before enabling Start.
   Verify delayed Pause from an older UI/notification cannot cancel the next
   session; rejected older starts must not tear down a newer queued service start.
   After an approved interrupted-insert fixture, startup must remain usable with a
   separate quarantine diagnostic. Starting a new session must not count that old
   uncertain record as a successful image or automatically retry its cleanup.
   After a saved frame followed by Pause abort with only unlink uncertainty,
   require PAUSED, ready=true and a usable next profile Start. ERROR_FILE_IO or
   database/provider errors must still fail. Wait diagnostics now include ready,
   sessionOpen, canStart, status and saved/quarantine counts; deadlines are unchanged.
6. Start again, return Home/use another app, and turn the screen off for at least
   five minutes (and later a sustained run spanning wake-lock renewal). After
   unlocking, inspect archived monotonic request times for continued sampling.
   No lock-screen takeover, hardware-key remapping or automatic boot restart is expected.
7. Open another camera or toggle Android camera privacy while recording. Expect
   error/safe stop, no runaway acquisition or false success; manually resume after
   resolving contention/permission. A 30-second timeout must release the wake lock.
8. Force-stop mid-capture only with the operator's approval; relaunch and verify
   recovery/idempotence, retained finalized originals, interrupted status and no
   auto-start. Repeat reboot with explicit permission. User intent is not live state.

## Storage And Sustained Evidence

The private index and any retained v1 archive use `run-as org.memotrace.recorder`
relative path `no_backup/recorder/`. MAIN's old 660 JPEGs/v1 index were explicitly
deleted at the user's request before new testing; the dated profile record describes
18 new ordinary JPEGs, not that archive. New original URIs and paths are in schema v2;
new images live publicly in Pictures/MemoTrace, not beside the index. See
[MediaStore protocol](media-storage.md).
Inspect it only while paused and drained. Debug `run-as` is normal debug APK
behavior, not a runtime exported service. Do not publish recordings or whole logs.
If extracting SQLite/JPEG evidence, use a private path outside the repository.

Use `frames.request_elapsed_ms` for observed request cadence within a session,
`request_wall_ms` for approximate calendar context, and `recovered` to distinguish
recovery-time commits. `saved_wall_ms` is not shutter time. Verify SHA-256 against
the corresponding original and inspect actual decode/quality. Do not infer exact
shutter timing from request scheduling or instantaneous UI count.

Low-space destructive filling belongs on an isolated emulator/test volume, not
the user's phone. Unit tests inject the exact 128 MiB boundary and below; native
storage tests run the real staged provider/index protocol, not an atomic
SQLite/MediaStore transaction. Any real ENOSPC test needs a separately
approved bounded filler location, cleanup and data safety plan. Never delete
unsynchronized originals to make this test pass.

For sustained runs record revision, APK hash, phone/OS, settings, duration, start
and end battery/temperature, storage delta, cadence percentiles, missed frames,
screen-off gaps, sharpness and cover false positives. Repeat without active ADB
or debugger. Locally inspected scoped `dumpsys activity services`, notification
and power state can confirm service/wake-lock ownership; they do not replace the
recorded frame timeline. Mark every unperformed experiment unavailable. Any
unresolved required behavior blocks a claim of device verification and merge.

## Same-Scene Benchmark

Use the same fixed phone position, lighting, text/detail targets, scene distance,
motion sequence and duration for each profile in the README matrix. The operator
selects profile, Start, records, Pause, waits until drained, then changes profile
and Starts a new session. Record leaf folder, requested/negotiated/actual dimensions,
Q, frame count, bytes, cadence distribution, legibility and cropping. Open the last
image with the real viewer control and also locate the profile-bearing album in
Gallery/My Files. 16:9 is not an equivalent field of view to 4:3.

Repeat order to reduce thermal/lighting bias. For battery claims, use matched
duration, display state and background services, no active ADB, multiple repetitions
and measured battery/temperature changes. Smaller JPEGs alone prove neither better
legibility nor lower total battery use. Do not claim a best profile without results.
After a separately authorized deletion/edit of a dedicated public test fixture,
return to MemoTrace and verify missing/changed status, historical count retention,
and ability to start another session. Do not delete ordinary archive images.
