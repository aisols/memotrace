# Recorder Device Verification

**Only the main agent/operator performs this procedure.** Implementation did not
access ADB or install/launch on the phone. Do not interpret assembled APKs or
Robolectric tests as hardware evidence. Reference: SM-A336B, Android 16/API 36.

## Identity And Build Outputs

- Application ID: `org.memotrace.recorder`
- Launcher: `org.memotrace.recorder.ui.MainActivity`
- Service: `org.memotrace.recorder.capture.RecorderService` (nonexported)
- App APK: `app/build/outputs/apk/debug/app-debug.apk`
- Test APK: `app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk`
- Runner: `org.memotrace.recorder.test/org.memotrace.recorder.IsolatedTestRunner`
- Resource prefix: `org.memotrace.recorder:id/`
- IDs: `start_recording`, `pause_recording`, `record_status`, `saved_count`,
  `last_saved`, `capture_interval`, `cover_shadow`, `recorder_scroll`.

Do not add debug exports or direct start-recording intent arguments for automation.
Starting the launcher does not grant recording consent. Tap the real Start control.

## Local And Instrumented Gates

After independently repeating the README's local command, pause any existing
recording and place a synthetic target in view. Instrumentation temporarily
replaces the normal app process; its Application uses UUID-isolated cache storage
and preferences, never `no_backup/recorder` or `record_state`. Tests clean their
own data; an unresolved outstanding callback leaves only its isolated test cache
for diagnosis instead of deleting a possibly live output.

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

Three tests must run, none skipped. Record failures, including camera/permission
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
2. Tap Start; grant camera and (preferably) notifications. Expect connecting, then
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

The archive is `run-as org.memotrace.recorder` relative path
`no_backup/recorder/`; schema/protocol is documented in recorder architecture.
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
storage tests run the real atomic commit. Any real ENOSPC test needs a separately
approved bounded filler location, cleanup and data safety plan. Never delete
unsynchronized originals to make this test pass.

For sustained runs record revision, APK hash, phone/OS, settings, duration, start
and end battery/temperature, storage delta, cadence percentiles, missed frames,
screen-off gaps, sharpness and cover false positives. Repeat without active ADB
or debugger. Locally inspected scoped `dumpsys activity services`, notification
and power state can confirm service/wake-lock ownership; they do not replace the
recorded frame timeline. Mark every unperformed experiment unavailable. Any
unresolved required behavior blocks a claim of device verification and merge.
