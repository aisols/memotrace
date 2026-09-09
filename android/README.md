# MemoTrace Android

Buildable, local-only adaptive JPEG recorder prototype for **Android 16 / API 36
and later**. API 36 is the only current test target; older Android versions are
deliberately not advertised by this first slice. Hardware behavior still needs
independent verification on the SM-A336B. No app was installed or launched during
implementation.

## Implemented Scope

- Visible, user-initiated camera foreground service, ongoing notification and Pause.
- Rear CameraX JPEG capture: 2000 ms baseline, 1000 ms during motion, one request
  including persistence at a time. Slow work reduces cadence rather than queuing.
- Sampled, latest-only low-resolution luma analysis. Cover suspicion is **SHADOW**:
  diagnostics only, never a reason to suppress, modify, or delete originals.
- App-private originals, SQLite metadata/checksums, startup recovery, low-space
  safe stop, persisted user intent and authoritative saved count/last-save time.
- Russian native Views, two large tremor-tolerant Start/Pause buttons, status and diagnostics.
  DOWN-anchored limited slip, UP-once and irreversible scroll/system cancellation;
  native performClick/accessibility actions, no long/double-press requirement.
  The page only scrolls when available height/text scaling requires it.

No network permission, upload, server, VLM, HEVC, speech, global keys,
accessibility service, kiosk, boot receiver, automatic camera restart, or
lock-screen takeover. Other applications remain accessible. Screen-off support
is the service's design, **not yet device evidence**. Faster sampling does not
fix motion blur. All finalized JPEGs are retained, including covered/dark scenes.
Uninstalling the application or clearing its data destroys this local archive;
there is no synchronization or backup in this slice.

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

Instrumented tests replace the Application with an isolated archive/preferences
implementation, including the real-camera test. Pause ordinary recording before
running instrumentation: Android may terminate the normal application process.
Use a synthetic/nonprivate scene. Never clear normal application data to reset
tests. See [device verification](docs/device-verification.md).

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
- [Quality gates, versions and local results](docs/quality.md)
- [Device verification and automation IDs](docs/device-verification.md)
- [Linux toolchain and ADB setup](docs/development.md)
- [Dependency provenance and notices](NOTICE.md)

## License

Original component code and documentation are `AGPL-3.0-only`. The complete
license is in the enclosing repository's `LICENSE`; include it when extracting
or distributing this component independently. Preserve the Gradle Wrapper's
Apache-2.0 headers and third-party notices. No private recordings or downloaded
SDK/dependency archives belong in Git.
