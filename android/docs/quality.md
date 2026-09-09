# Android Quality Gates

## Toolchain

| Tool/dependency | Pin |
| --- | --- |
| Gradle Wrapper | 8.13 |
| Android Gradle Plugin | 8.13.2 |
| Kotlin | 2.2.21 |
| Java toolchain | 21; local Ubuntu 21.0.12+8, CI Temurin 21.0.12+8 |
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
matrix; they do not suppress Android safety checks. The one UseKtx suppression
preserves SharedPreferences.commit's Boolean failure result, which KTX discards.
Lint otherwise treats warnings as errors, with no baseline.

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
were removed and no tests were skipped; device retry remains main-agent-owned.

Implementation-owner verification of that fixture (no device access):

```bash
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug spotlessCheck :app:assembleDebugAndroidTest --rerun-tasks
```

Passed with 76 tasks executed and all 37 app-local tests passing, zero skipped.
Lint found no issues; formatting and instrumentation APK signature verification
passed. Production sources contain no `FLAG_KEEP_SCREEN_ON`. These local checks
do not execute the runner's device lifecycle callback; the initially unlocked
phone retry is still required.

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
Independent review, latest-revision CI, and the main agent's actual device evidence
remain required before merge. Existing server/contracts have no executable targets;
cross-component tests are not applicable to this no-network slice.
The Gradle action v5.0.0 reference is the peeled official commit
`4d9f0ba0025fe599b4ebab900eb7f3a1d93ef4c2`, resolved using
`git ls-remote https://github.com/gradle/actions.git 'refs/tags/v5.0.0*'`, not its
annotated tag object `f236b35da9d031e13b1005234ebe4392ed54c580`.
