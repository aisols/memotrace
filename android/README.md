# MemoTrace Android

Buildable, offline adaptive JPEG recorder prototype for **Android 16 / API 36
and later**. API 36 is the only current test target; older Android versions are
deliberately not advertised by this first slice. Bounded SM-A336B observations and
remaining hardware limits are recorded in the
[2026-09-09 main-agent evidence](docs/verification-2026-09-09.md).
The implementation owner did not install or launch the app.

## Implemented Scope

- Visible, user-initiated camera foreground service, ongoing notification and Pause.
- Rear CameraX JPEG capture: 2000 ms baseline, 1000 ms during motion, one request
  including persistence at a time. Slow work reduces cadence rather than queuing.
- Sampled, latest-only low-resolution luma analysis. Cover suspicion is **SHADOW**:
  diagnostics only, never a reason to suppress, modify, or delete originals.
- Six JPEG profiles, default 1440x1080 Q90, selectable only after Pause drains.
  Every Start creates a new profile/session Gallery folder.
- One original in public MediaStore Pictures after explicit first-Start consent;
  private schema-v2 SQLite metadata/checksums, recovery, low-space safe stop,
  persisted selection/intent, actual dimensions, bytes and last-image viewer.
- Russian native Views, large tremor-tolerant Start/Pause/profile/view controls, status and diagnostics.
  DOWN-anchored limited slip, UP-once and irreversible scroll/system cancellation;
  native performClick/accessibility actions, no long/double-press requirement.
  The page only scrolls when available height/text scaling requires it.

No network permission, upload, server, VLM, HEVC, speech, global keys,
accessibility service, kiosk, boot receiver, automatic camera restart, or
lock-screen takeover. Other applications remain accessible. A bounded screen-off
observation is recorded in the [main-agent evidence](docs/verification-2026-09-09.md),
not an endurance guarantee. Faster sampling does not fix motion blur. All finalized
JPEGs are retained, including covered/dark scenes.
Gallery, Google Photos and OneDrive may independently back up these public images.
MemoTrace's lack of network permission does not prevent that. Public images may
survive uninstall/data clearing, but the private index and legacy private archive
are lost; reinstall cannot restore their index/ownership. Shipped v1 private files
are preserved on upgrade, not exported or made viewable automatically.
No MemoTrace synchronization/backup or release publishing in this debug prototype.

## Compare Profiles

| Stable ID | Requested JPEG | Purpose |
| --- | --- | --- |
| `v1-4000x3000-q95` | 4000x3000 Q95, 4:3 | Reference |
| `v1-4000x3000-q80` | 4000x3000 Q80, 4:3 | Compression control |
| `v1-1920x1080-q90` | 1920x1080 Q90, 16:9 | Wide |
| `v1-1920x1080-q80` | 1920x1080 Q80, 16:9 | Wide/compression |
| `v1-1440x1080-q90` | 1440x1080 Q90, 4:3 | Experimental lower-volume default |
| `v1-1440x1080-q80` | 1440x1080 Q80, 4:3 | Compact/compression |

Choose profile, Start, record a repeatable scene, Pause, wait for drain, then choose
the next profile and Start. Use **Open last JPEG** or Gallery/My Files at
`Pictures/MemoTrace/<profile>/<profile>_<UTC-time>_<session-UUID>/`.
16:9 may crop the top/bottom of the 4:3 view. CameraX uses closest-lower-then-higher
fallback; compare actual dimensions, not requested size alone. No application
Bitmap rescale/re-encode. Q is a CameraX request, not a universal quality score.
No battery/legibility superiority is claimed without benchmarking.

## Build And Verify

Run from `android/`, with JDK 21, `ANDROID_HOME`, accepted SDK terms, API 36 and
Build-Tools 36.0.0. No parent configuration, sibling source, or live server is
needed. The wrapper downloads its checksum-pinned official Gradle distribution.

```bash
./gradlew --no-daemon :capture-core:check :app:testDebugUnitTest :app:lintDebug spotlessCheck :app:assembleDebug :app:assembleDebugAndroidTest
```

`./gradlew spotlessApply` formats Kotlin/build scripts; it does not replace the
check. `:capture-core:check` includes tests, JaCoCo report, and coverage enforcement.
Independent test-result finalizers reject absent/empty results and every skipped
test; a separate task rejects missing coverage inputs even when JaCoCo would skip.
The root workflow runs the command above; it does not run hardware tests.

Only the coordinating main agent/operator runs the device command:

```bash
./gradlew :app:connectedDebugAndroidTest
```

Host safety is separate from test Application isolation. Component defaults retain
both APKs and forbid uninstall-on-incompatibility; a prerequisite and first-action
gate reject unsafe/missing effective values before DeviceProvider/install. Run
`./gradlew :app:verifyConnectedTestSafety :app:verifyConnectedTestSafetyWiring`
without a device. See [host safety](docs/connected-test-safety.md) for override
regressions, the pinned uninstall audit, explicit flags and direct-ADB alternative.
MAIN confirmed the target package was absent after the earlier failed connected
run; its runner-stage ledger retention did not protect against host teardown.

Instrumented tests replace the Application with a UUID-isolated archive/preferences
and `Pictures/MemoTrace-instrumentation/<run-UUID>/` MediaStore namespace, including
real-camera tests. Cleanup requires a private per-run creation ledger (identity
before insertion, returned URI afterward), then exact-identity assert/delete
batches after drain. Owner/path/UUID format alone does not prove fixture creation.
Ledger removal additionally requires physical unlink evidence from a retained
descriptor; missing rows alone are insufficient. Uncertain cleanup reports and
retains provenance, never scans/deletes other paths. Native test pass counts do
not imply all test residue is gone; the lost-witness test retains a diagnostic ledger.
Normal Pictures/MemoTrace and the private archive are never cleanup targets. Pause ordinary recording before
running instrumentation: Android may terminate the normal application process.
Use a synthetic/nonprivate scene. Never clear normal application data to reset
tests. Test frames are public too: approve the scene and consider independent
cloud backup settings. See [device verification](docs/device-verification.md).

Full history availability checks defer until Pause has drained; an idle check
temporarily gates Start. Trash/missing/changed files retain historical metadata,
not viewing eligibility. Start reserves the selected profile before service delivery.
Pause commands target that session; stale commands cannot stop its replacement.
At startup, old unvalidated media with missing/unproven cleanup becomes a retained
quarantine tombstone. Its separate diagnostic count is not a saved-image count;
new sessions are allowed without deleting uncertain artifacts. Quarantine is not
retried on every startup. Current write, DB and provider failures remain fatal.
After writer-drained Pause/abort, typed unlink uncertainty is also quarantined
without disabling the next Start. FUSE fstat ENOENT means UNKNOWN, not proven
unlink; STILL_LINKED is reported separately. Expected test-cleanup uncertainty is
reported with retained ledgers rather than crashing instrumentation finish.
The [A33 gallery test attempt](docs/a33-gallery-failure-2026-09-09.md) failed before
this adaptation; the adapted native tests still require MAIN's reviewed rerun.

## Layout

| Location | Responsibility |
| --- | --- |
| `capture-core/` | Pure JVM scheduler, state, motion/cover metrics and exhaustive policy tests |
| `app/.../capture/` | Service lifecycle, bounded orchestration, CameraX side-effect boundary |
| `app/.../storage/` | Durable local index, streaming checksum, recovery and safe stop |
| `app/.../ui/` | Native accessible controls and honest status |
| `app/src/test/` | Robolectric native SQLite/filesystem and fake-camera service/UI regressions |
| `app/src/androidTest/` | Real Android storage, UI and foreground-camera lifecycle tests |

The JVM module is justified by Android-free policy testing and its explicit
coverage gate. A separate Android recorder module would add no useful isolation.
Future sync/speech packages should be added only with working implementations.

`python3 tools/verify-quality-failures.py --temp-parent /tmp/opencode` repeats the
same clean command in an isolated positive copy and six negative copies. It never
mutates source tests; see the quality document for expected gate failures.

## Documentation

- [Architecture and recovery protocol](docs/recorder-architecture.md)
- [MediaStore, schema v2 and migration](docs/media-storage.md)
- [Quality gates, versions and local results](docs/quality.md)
- [Device verification and automation IDs](docs/device-verification.md)
- [Connected-test host safety](docs/connected-test-safety.md)
- [Linux toolchain and ADB setup](docs/development.md)
- [Dependency provenance and notices](NOTICE.md)

## License

Original component code and documentation are `AGPL-3.0-only`. The complete
license is in the enclosing repository's `LICENSE`; include it when extracting
or distributing this component independently. Preserve the Gradle Wrapper's
Apache-2.0 headers and third-party notices. No private recordings or downloaded
SDK/dependency archives belong in Git.
