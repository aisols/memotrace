# Android Quality Gates

## Connected Host Safety

The [host uninstall audit and commands](connected-test-safety.md) are a separate
gate from runtime fixture isolation. MAIN confirmed the package absent after the
failed connected run; runner-stage ledger retention did not prove survival past
AGP/UTP teardown. Component defaults now retain APKs and forbid incompatible-APK
uninstall, with prerequisite and first-action guards on connected test tasks.

Implementation-owner local verification on 2026-09-09, without device access:

| Check | Result |
| --- | --- |
| `:app:verifyConnectedTestSafety` default | Passed |
| `:app:verifyConnectedTestSafetyWiring` default | Passed on actual debug/aggregate tasks; only safety guards executed |
| `-Pandroid.injected.androidTest.leaveApksInstalledAfterRun=false` | Exit 1, safety gate rejected before DeviceProvider/install |
| `-Pandroid.experimental.testOptions.uninstallIncompatibleApks=true` | Exit 1, safety gate rejected before DeviceProvider/install |
| Isolated debug and release-test-build-type wiring | Both passed, including actual AGP factory flag checks |
| Seven isolated unsafe/missing/empty/inline-guard negatives | All rejected as expected, no device actions |
| Unchanged README command with `clean` | Passed, 101 tasks executed (one added no-device wiring task) |
| Core/app unit tests | 23 + 81 passed; zero skipped/failed/errors |
| Core coverage | 123/123 lines, 151/152 branches; unchanged 90/80 minimum gates |
| Existing quality-negative verifier | Positive plus all six negative cases passed expected checks |

Safety evidence: `/tmp/opencode/memotrace-connected-safety-y391_w5z/`.
Existing quality-gate repetition: `/tmp/opencode/memotrace-quality-x3cccv4e/`.
An initial safety-verifier run expected the custom diagnostic for empty retention;
AGP correctly rejected the empty boolean earlier during plugin configuration. The
verifier now requires that exact AGP diagnostic for this case; other negatives
still require the custom safety rejection. No gate was weakened or test disabled.

CI retains its existing full quality command and adds the independent no-device
safety regression script. No runtime/native/FUSE source, versionCode or dependency
pin changed in this correction. App/test APK hashes remain the FUSE hashes below.
No connected task or DeviceProvider action was executed by the implementation
owner. MAIN owns review and the future device rerun.

## Profile Storage Review Fixes

Implementation-owner local verification on 2026-09-09 for versionCode 2/versionName
0.2.0 including the A33/FUSE unlink and Pause adaptation, not independent review or
device evidence. The toolchain pins and all
existing gates are unchanged. [Storage protocol and limitations](media-storage.md)
supersede the v1 private-file protocol for new captures; historical evidence below
and `verification-2026-09-09.md` are not new-profile device results.

```bash
./gradlew --no-daemon clean :capture-core:check :app:testDebugUnitTest :app:lintDebug spotlessCheck :app:assembleDebug :app:assembleDebugAndroidTest
python3 tools/verify-quality-failures.py --temp-parent /tmp/opencode
```

Both passed using the documented JDK/SDK environment. Clean command: 100 tasks
executed. Negative verifier: isolated positive succeeded, all six negative copies
failed for their intended nonempty/zero-skips gate diagnostic. No verifier change
was needed. Latest local evidence: `/tmp/opencode/memotrace-quality-swlisarr/`.
`/tmp/opencode/memotrace-quality-eyfhg1_p/` is the preceding quarantine iteration.
Earlier `/tmp/opencode/memotrace-quality-_5iq4crl/`, `/tmp/opencode/memotrace-quality-bq4qx9w_/` and
`/tmp/opencode/memotrace-quality-_lh7u0ov/` predate the latest corrections.

| Check | Local result |
| --- | --- |
| Pure-core tests | 23 passed, zero skipped/failed/errors |
| App tests | 81 passed, zero skipped/failed/errors |
| Core lines | 123/123, 100% |
| Core branches | 151/152, 99.34% |
| Required core gates | >=90% lines, >=80% branches, unchanged; no exclusions |
| Android lint | Passed, no issues |
| Spotless/ktlint | Passed |
| App and instrumentation APK assembly | Passed |
| Both APK signatures | Build-Tools 36.0.0 apksigner verified v2 signatures |
| App identity/permissions | aapt2 confirms org.memotrace.recorder, 2/0.2.0, API 36; no network/broad photo permission |
| Instrumentation execution | Not run by implementation owner; ten tests compiled |
| Previous-revision A33 run by MAIN | 2 passed, 8 failed, zero skipped; runner cleanup then crashed. Adaptation rerun pending |
| Hosted CI and independent review | Not performed by implementation owner |

App tests comprise 22 storage/migration/fault/reconciliation, 11 ContentResolver
adapter contract/resource, 1 pinned CameraX stream/scratch contract, 3 disk-barrier,
27 lifecycle, 8 profile/consent/viewer and 9 gesture/accessibility/layout tests.
Coverage also includes immutable core profile/session tests; existing scheduling
and tremor tests remain. Native-graphics unit tests exercise wrapped dialog text
and scrolling at 2x font in a 240x360 dp window. No safety lint is suppressed;
UseKtx suppressions only retain Boolean SharedPreferences commit failure signals.

Fakes test ownership predicates, null/error responses, resource closure, every
index/provider crossing, same-size edit limitation and non-blocking historical
tombstones. They do not prove Android MediaProvider durability, filesystem power
loss, OEM negotiated dimensions or encoder quality. Ten native tests compile:
synthetic MediaStore save/open/decode/recovery, idle UI recreation, background
foreground-service capture/Pause, all six real profiles, pending-delete assertion
protection on published/moved items, creation-ledger/lost-URI sentinel protection,
concurrent publication/deletion with inode unlink evidence, missing-row/lost-witness
ledger retention, trash/restore, and insert-before-first-open Application recovery.
The last case accepts eager or lazy providers only with ready=true, zero successful
saves and either proven removal or a retained quarantine tombstone; recovery
cannot call openWrite or force file materialization. UUID-isolated private
state and creation-ledger-based MediaStore cleanup are mandatory; normal archives
are never test cleanup targets. Operator scene/backup approval and initial unlock
remain prerequisites, with the existing scoped test-only keep-awake fixture.

SDK XML/parser and unstripped CameraX JNI warnings remain visible/nonfatal, as in
the previous slice. Main owns latest-revision device, CI and final merge gates.

Both local verification runs of the current FUSE adaptation passed; no local
failure or skipped test remains. The earlier quarantine iteration had one failing adapter regression: the test
provider opened every file read/write even for an `r` request, creating the missing
fixture instead of returning FileNotFoundException. Its mode handling now follows
the request; the lazy destination fake also materializes only at openWrite.
That test was corrected, not disabled. Earlier formatting/inference issues were
also fixed without suppression. The subsequent MAIN-owned native run failed as
recorded in [A33 gallery evidence](a33-gallery-failure-2026-09-09.md). Read/preserved
that JUnit report before clean builds removed it. The adapted native provider
tests have only compiled; the AOSP audit and local checks are not a Samsung pass.

Regression details: plain delete is replaced by a non-yielding assert/delete
batch with expected counts and no exception continuation/fallback. Publication
acknowledgement survives subsequent absence/access loss. Trash retains historical
metadata without viewing eligibility. Fatal SQLite refresh failure stops/drains
an active service even if IO subsequently recovers and a late frame commits.
Full history checks defer through recording and post-Pause disk drain; a blocking
old-item fake cannot consume the active camera watchdog. Start snapshots/reserves
on main before service delivery, rejects stale/forged/duplicate commands and
profile changes, and releases on cancellation/launch failure without process replay.

Latest regressions drive real UI Start-A/Pause/Start-B listeners before service
delivery, require no queued generic Pause after synchronous cancellation, and
verify service-level start-ID forwarding before accepting B. UI and notification
Pause are session-scoped; notification PendingIntents are distinct across sessions.
Unknown/rejected service commands and internal stops are all start-ID-aware.

Cleanup now requires a retained, initially linked regular-file descriptor with
stable device/inode and zero link count, not only a successful batch or absent
provider row. A fake provider models deleted rows with still-linked artifacts;
tests require retained quarantine/provenance and a closed witness, not a successful
save. Robolectric fstat itself returns stub zero values, so these contract
tests inject inode/link-count facts rather than claiming Android filesystem proof.
Native races drain both workers before testing the retained inode, then verify
ledger removal only after proven unlink, or ledger retention plus instrumentation
status reporting on uncertainty. The missing-row/lost-witness test intentionally
retains its private diagnostic ledger. A native test pass count is NOT a claim
of residue-free cleanup. OEM/FUSE evidence limitations remain MAIN-owned gates.

UnlinkWitness now reports PROVEN_UNLINKED / STILL_LINKED / UNKNOWN. Adapter tests
inject fstat ENOENT both initially and after deletion, requiring UNKNOWN and closed
FDs; EBADF/EIO/EACCES and known non-ENOENT descriptor-open causes remain real errors.
The lifecycle regression saves one frame, pauses/aborts another with UNKNOWN,
requires ready/PAUSED, keeps saved count unchanged and quarantine count separate,
then selects a new profile and successfully starts/saves again. Companion tests
keep ERROR_FILE_IO fatal despite successful quarantine, and keep EBADF and failed
quarantine DB updates fatal. No CameraX ordering, cadence or watchdog change.

Expected fixture uncertainty now returns/logs per-fixture residue reports rather
than throwing through runner finish. The runner preserves JUnit output/results,
appends unresolved-cleanup diagnostics and always calls super.finish. Real provider,
identity/DB/close errors or an undrained writer set a strong failed-run report with
cause/stack; they are not ignored. Isolated index/preferences stay when residue
remains. Native row, ownership, sentinel, trash and race assertions are retained,
with tri-state evidence replacing the unsupported universal POSIX assumption.
These runner/device behaviors await MAIN's reviewed rerun.

The earlier global fail-closed treatment of absent unvalidated pending output was
a recoverability regression, not an acceptable limitation. Startup now persists
state=2 (QUARANTINED), availability=CLEANUP_UNPROVEN, with identity/URI/provenance
intact. Quarantine is excluded from successful/available/last-image totals, shown
separately through `quarantined_count`, and never automatically retried or deleted.
Regression expectations at prepared/failed-insert were corrected to require
successful recovery, not repeated failure. Tests cover lazy insert-before-open,
idempotent startup, no provider access for already-quarantined rows, new capture
count=1 rather than counting uncertainty, UI diagnostics, and fatal SQLite failure
while attempting the quarantine update. After acknowledged abort and writer drain,
typed cleanup uncertainty also quarantines without disabling the next Start.
Namespace/ownership errors, real provider failures, invalid validated pending data
and actual current-session IO (including ERROR_FILE_IO) remain fatal;
recovery still rejects live-writer use. No broad exception-to-quarantine conversion,
path scan or uncertain-artifact deletion. Test fixture cleanup scope is unchanged.

Local clean-build SHA-256 (debug artifacts, not a release):

- `app-debug.apk`: `c4dfa2499399b95525af7e260387d8e1ea9618efc5095d59ce47b865bf5bc756`
- `app-debug-androidTest.apk`: `23bb3896da7c4bc63cae6bd677a351eb8599706f9dafc6cea303fc80a0afbd22`

## Toolchain

| Tool/dependency | Pin |
| --- | --- |
| Gradle Wrapper | 8.13 |
| Android Gradle Plugin | 8.13.2 |
| Kotlin | 2.2.21 |
| Java toolchain | 21; local Ubuntu 21.0.12+8, CI Temurin SemVer 21.0.12+8.0.LTS (JDK build +8) |
| min/compile/target SDK | 36/36/36 |
| Installed API 36 platform | revision 2 |
| Build-Tools | 36.0.0 |
| CameraX camera2/lifecycle | 1.5.3 |
| AndroidX core-ktx / lifecycle-service | 1.17.0 / 2.9.4 |
| JUnit / Robolectric | 4.13.2 / 4.16.1 |
| AndroidX test runner/rules, ext.junit, Espresso | 1.7.0, 1.3.0, 3.7.0 |
| JaCoCo | 0.8.13 |
| Spotless / ktlint | 7.2.1 / 1.7.1 |

Selected from official [AGP 8.13 compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes),
[Kotlin compatibility](https://kotlinlang.org/docs/gradle-configure-project.html),
[Gradle Java compatibility](https://docs.gradle.org/8.13/userguide/compatibility.html),
and [CameraX stable releases](https://developer.android.com/jetpack/androidx/releases/camera).
These are intentional stable API-36 pins, not assertions that they are the latest.
The four explicit dependency-update advisory suppressions preserve this tested
matrix; they do not suppress Android safety checks. The SharedPreferences UseKtx suppressions
preserve SharedPreferences.commit's Boolean failure result, which KTX discards.
Lint otherwise treats warnings as errors, with no baseline.

### Exact Temurin CI Pin

The [official Adoptium API](https://api.adoptium.net/v3/assets/version/%5B21.0.12%2C21.0.13%29?project=jdk&vendor=adoptium&heap_size=normal&sort_method=DEFAULT&sort_order=DESC&os=linux&architecture=x64&image_type=jdk&release_type=ga&jvm_impl=hotspot&page_size=20&page=0)
identifies the Linux x64 HotSpot JDK GA release `jdk-21.0.12+8` with
`version_data.semver = 21.0.12+8.0.LTS`, `build = 8`, and
`openjdk_version = 21.0.12+8-LTS`. The separate `21.0.12+101.0.LTS` entry is
release `jdk-21.0.12.1+1`, not the requested +8 build.
The [pinned setup-java matcher](https://github.com/actions/setup-java/blob/dded0888837ed1f317902acf8a20df0ad188d165/src/util.ts)
uses `semver.compareBuild` for exact pins containing build metadata, so the
workflow uses the complete `21.0.12+8.0.LTS` identifier, not a floating Java 21 range.

Main-agent report: draft PR #2's first hosted run failed in `actions/setup-java`
because the former `21.0.12+8` pin did not match the published SemVer. Gradle
checks had not started. This correction changes only the CI version identifier;
the JDK +8 selection and all verification gates are retained. Hosted rerun remains
main-agent-owned; no runtime/test sources or device APKs were changed or rebuilt.

### Isolated CI SDK Inputs

[Hosted run 34341346464](https://github.com/aisols/memotrace/actions/runs/34341346464)
completed tests, coverage, style and both APK assemblies, but failed `:app:lintDebug`
with `OldTargetApi` at `targetSdk = 36`. It used `/usr/local/lib/android/sdk`;
the [runner image inventory](https://github.com/actions/runner-images/blob/ubuntu24/20260831.293/images/ubuntu/Ubuntu2404-Readme.md#android)
includes API 37 platforms. The locally isolated API-36 checks passed as recorded
below; that is not a hosted CI pass.

Source confirmation for AGP 8.13.2's lint 31.13.2:
`GradleDetector.checkTargetSdkVersion` / `TargetSdkCheck.checkTargetSdk` in the
[lint-checks sources](https://dl.google.com/dl/android/maven2/com/android/tools/lint/lint-checks/31.13.2/lint-checks-31.13.2-sources.jar)
compare against `LintClient.highestKnownApiLevel` in the
[lint-api sources](https://dl.google.com/dl/android/maven2/com/android/tools/lint/lint-api/31.13.2/lint-api-31.13.2-sources.jar).
That is the maximum of installed platforms (including previews) and
`SdkVersionInfo.HIGHEST_KNOWN_STABLE_API`, which is 36 in the
[pinned sdklib sources](https://dl.google.com/dl/android/maven2/com/android/tools/sdklib/31.13.2/sdklib-31.13.2-sources.jar).

The workflow now gives the [pinned setup action](https://github.com/android-actions/setup-android/blob/9fc6c4e9069bf8d3d10b2204b1fb8f6ef7065407/src/main.ts)
a fresh `${{ runner.temp }}/android-sdk`, with both SDK variables set in **step**
`env` (the `runner` context is unavailable in job `env`). The action reads
`ANDROID_SDK_ROOT`, creates directories through its archive extractor, installs
official command-line tools `16111833` and the declared `platform-tools`,
`platforms;android-36`, `build-tools;36.0.0` packages, then exports both
`ANDROID_HOME` and `ANDROID_SDK_ROOT` for subsequent steps. The SDK is not cached;
installed revisions are logged, not fabricated. SDK Manager resolves revisions
within these package IDs; this is an isolated API baseline, not a byte-for-byte lock.
No host SDK files are removed or metadata altered.

`OldTargetApi` remains active with warnings as errors: targeting below the declared
API-36 baseline still fails lint. SDK/target upgrades require explicit reviewed
matrix changes, behavior review and device verification, not unrelated runner-image
updates. No lint suppression, baseline, diagnostic filtering or gate reduction is
added. Independent review and the main agent's final hosted rerun remain pending;
this environment-only correction has not established a new CI or device pass.

## Wrapper Provenance

Bootstrapped the official distribution, compared its SHA-256 to Gradle's published
HTTPS checksum, generated the wrapper using that Gradle, then ran the wrapper.
Both the distribution checksum property and generated wrapper files belong here.

- [Distribution](https://services.gradle.org/distributions/gradle-8.13-bin.zip)
- [Published distribution SHA-256](https://services.gradle.org/distributions/gradle-8.13-bin.zip.sha256):
  `20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78`
- [Published wrapper JAR SHA-256](https://services.gradle.org/distributions/gradle-8.13-wrapper.jar.sha256):
  `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`

Manual wrapper regeneration: `./gradlew wrapper`; compare the JAR with
`sha256sum gradle/wrapper/gradle-wrapper.jar`. Downloaded archives, caches, debug
signing keys and SDKs are not source artifacts. Never bypass wrapper validation.

## Required Local Checks

Run from `android/`:

```bash
./gradlew --no-daemon :capture-core:check :app:testDebugUnitTest :app:lintDebug spotlessCheck :app:assembleDebug :app:assembleDebugAndroidTest
```

For a clean repetition, prefix the task list with `clean`. Build configuration
does not source the host helper; standard JDK/SDK environment variables suffice.
Android's own `.editorconfig` prevents dependence on a parent formatting file.

`capture-core:check` includes **>=90% line and >=80% branch coverage** over all
production JVM policy classes, without exclusions. Line coverage guards forgotten
policy paths, including touch policy; branch coverage requires decisions/hysteresis/error
paths rather than just happy-path execution. These are component-local minimums,
not whole-app percentages and not proof of correctness. They must be independently
reviewed alongside threshold-boundary, busy/late/failure and SHADOW-invariance
assertions. Do not lower gates to accommodate missing tests.

`capture-core:testResults` and `app:testDebugUnitTestResults` are separate,
always-checked finalizer tasks registered outside Test/JaCoCo actions. They require
test class files, XML result files, total tests >0, zero skips (including individual
`@Ignore`) and zero failures/errors. They run for NO-SOURCE and up-to-date Test
tasks, not only inside a possibly skipped `doFirst`. `capture-core:verifyCoverageInputs`
independently requires nonempty execution data and production class files before
the JaCoCo report/coverage tasks. No assertion-count constant, code exclusion or
coverage-threshold reduction is used.

## Negative Gate Verification

From `android/`, with the same JDK/SDK environment and Python 3 standard library:

```bash
python3 tools/verify-quality-failures.py --temp-parent /tmp/opencode
```

The script creates fresh component-only temporary copies, excluding generated
build/cache/local configuration, and runs the **entire standard command with
`clean`** in each copy. Only copied test sources are removed or bulk-annotated
with `@org.junit.Ignore`. Each negative must exit nonzero with the matching
test-results gate diagnostic, not merely an unrelated compile/format failure.
Copies and logs remain in the printed temporary evidence directory. Source tests,
Git state, real archives and phone settings are untouched.

Implementation-owner gate run on 2026-09-09, before the batched-motion follow-up
(the gate implementation is unchanged):

| Isolated case | Exact outcome |
| --- | --- |
| Unmodified positive | Exit 0, full clean suite passed |
| capture-core: absent tests | Exit 1, test-results gate: no test class files |
| capture-core: all tests ignored | Exit 1, test-results gate: skipped tests |
| capture-core: one ignored test | Exit 1, test-results gate: skipped tests |
| app: absent tests | Exit 1, test-results gate: no test class files |
| app: all tests ignored | Exit 1, test-results gate: skipped tests |
| app: one ignored test | Exit 1, test-results gate: skipped tests |

Local transient evidence: `/tmp/opencode/memotrace-quality-yn0mn_dv/`. This is
implementation-owner evidence, not the main agent's independent repetition.

## Reports

- `capture-core/build/reports/tests/test/index.html`
- `capture-core/build/reports/jacoco/test/html/index.html` (also XML/CSV alongside)
- `app/build/reports/tests/testDebugUnitTest/index.html`
- `app/build/reports/lint-results-debug.html`
- `app/build/reports/androidTests/connected/debug/index.html` after device tests

Android lint intentionally treats the Android-free JVM module as external;
Kotlin compilation, ktlint, tests and JaCoCo verify that module. There are no
Android side effects in it. No test is skipped to produce a green build.

## Verification Ownership

Implementation-owner clean verification on 2026-09-09 (Ubuntu 24.04 amd64,
JDK 21.0.12, installed SDK above), not independent verification:

| Check | Result |
| --- | --- |
| Clean README command, prefixed with `clean` | Passed after batched-motion fix, all 100 tasks executed |
| Pure policy JUnit tests | 21 passed, zero skipped/failed |
| App local tests | 37 passed (12 storage, 14 lifecycle, 3 disk queue, 8 touch/accessibility/layout), zero skipped/failed |
| JaCoCo production policy lines | 98/98, 100% |
| JaCoCo production policy branches | 149/150, 99.33% |
| Android lint | No issues found |
| Spotless/ktlint | Passed |
| App and instrumentation APK assembly | Passed; both APK signatures verified with Build-Tools apksigner |
| Gradle distribution and wrapper JAR checksum | Matched official published SHA-256 |
| Git diff whitespace | Passed; changes left unstaged, no Git/GitHub mutation |

The three instrumented
tests are compiled into a separate APK but **not executed by the builder**.
They cover native storage/recovery/checksum, UI recreation/idle pause, and real
foreground camera capture continuing after Activity stop and then pausing using
native accessibility actions. The real Button nodes must be enabled, clickable,
visible and have ACTION_CLICK, with no hidden ancestors.
The latter requires a functioning API-36 rear camera and a nonprivate test scene.

Main-agent update before the test-only screen-timeout fixture: independent clean
verification passed all 58 local tests and all six negative gate cases. The first
real connected run passed storage but failed UI/capture (2 of 3 tests) with
`NoActivityResumed` / ActivityScenario STOPPED. Main observed secure keyguard showing
and the screen off after timeout. This is a documented environment-blocked run,
not a passed hardware recorder gate. See device-verification.md for the required
initial user unlock and scoped instrumentation-only window flag. No assertions
were removed and no tests were skipped. The subsequent unlocked 3/3 retry and
bounded manual screen-off observation are recorded in the
[2026-09-09 main-agent evidence](verification-2026-09-09.md).

Implementation-owner verification of that fixture (no device access):

```bash
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug spotlessCheck :app:assembleDebugAndroidTest --rerun-tasks
```

Passed with 76 tasks executed and all 37 app-local tests passing, zero skipped.
Lint found no issues; formatting and instrumentation APK signature verification
passed. Production sources contain no `FLAG_KEEP_SCREEN_ON`. These local checks
do not execute the runner's device lifecycle callback; the subsequent main-agent
device retry is recorded in the [dated evidence](verification-2026-09-09.md).

Known nonfatal tool output: AGP's SDK parser warns about installed command-line
tools' XML schema 4 versus parser schema 3; the API-36 builds resolve successfully.
Without an NDK, the two CameraX JNI libraries are packaged without debug-symbol
stripping. Neither warning is hidden or evidence of a device pass.

Robolectric storage tests execute native SQLite plus host NIO rename/fsync, with
synthetic free-space statistics. They inject death after prepared, file-synced,
renamed and committed boundaries, reopen, and recover twice. They are not power-loss
proof for Android filesystems. Fake-camera application tests exercise lifecycle,
one-shot callbacks, busy slots, teardown, timeout, durable-save-only status,
disk failure and wake-lock release without touching camera hardware.
Additional tests block an actual serial executor writer across abort/dispose,
verify typed CameraX file IO failures, invoke the real dependency's scratch-name
factory, and enforce startup-only recovery. UI tests use Robolectric's native
graphics for real text metrics/visibility, an isolated 2x-font Activity at 240x360 dp,
fully reachable/unclipped labels, native Button nodes/actions, actual ScrollView
interception, target anchoring/slip, cancellation and one-shot release. They never
change global device font settings.
The batched-motion regression first reproduced the false-click defect before the
adapter fix. `MotionEvent.addBatch` tests now cover historical excursions on MOVE
and retained UP history, bounded batches, persistent cancellation, DOWN pointer-ID
tracking/replacement rejection, and delivery through a real ScrollView. Historical
samples are processed oldest-first before current coordinates; returning inside
cannot revive an earlier cancelled gesture.

`.github/workflows/android.yml` runs the local command on Ubuntu 24.04 with pinned
action commits and tool versions. It assembles instrumentation but does not claim
hosted runners are the reference device. Hosted CI has not been run by the builder.
Independent review and bounded main-agent device observations are recorded in the
[dated evidence](verification-2026-09-09.md), with remaining limitations. Latest-revision
CI and unresolved required checks remain merge gates; [PR #2](https://github.com/aisols/memotrace/pull/2)
is authoritative for the pending hosted rerun. Existing server/contracts have no
executable targets; cross-component tests are not applicable to this no-network slice.
The Gradle action v5.0.0 reference is the peeled official commit
`4d9f0ba0025fe599b4ebab900eb7f3a1d93ef4c2`, resolved using
`git ls-remote https://github.com/gradle/actions.git 'refs/tags/v5.0.0*'`, not its
annotated tag object `f236b35da9d031e13b1005234ebe4392ed54c580`.
